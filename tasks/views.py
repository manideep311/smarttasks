from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .ai import break_down_task, parse_task_text
from .errors import error_response, not_found, validation_error
from .idempotency import idempotent
from .models import Task
from .serializers import TaskSerializer

PRIORITY_LEVELS = [value for value, _ in Task.PRIORITY_CHOICES]
RECURRENCE_VALUES = (None, 'daily', 'weekly', 'monthly', 'yearly')


def subtask_not_allowed(task):
    return error_response(
        'SUBTASK_NOT_ALLOWED',
        'A subtask cannot have its own subtasks',
        [{'field': 'id', 'issue': f'task {task.pk} is already a subtask of task {task.parent_id}'}],
        status.HTTP_400_BAD_REQUEST,
    )


def body_must_be_object():
    return error_response(
        'VALIDATION_ERROR',
        'Validation failed',
        [{'field': 'body', 'issue': 'must be a JSON object'}],
        status.HTTP_400_BAD_REQUEST,
    )


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    filterset_fields = ['completed', 'priority']
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'updated_at', 'due_date', 'title']
    ordering = ['-created_at', '-id']

    def find_task(self):
        try:
            return self.get_object()
        except Http404:
            return None

    @idempotent
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return validation_error(serializer.errors)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        task = self.find_task()
        if task is None:
            return not_found(kwargs.get('pk'))
        return Response(self.get_serializer(task).data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        task = self.find_task()
        if task is None:
            return not_found(kwargs.get('pk'))
        serializer = self.get_serializer(task, data=request.data, partial=partial)
        if not serializer.is_valid():
            return validation_error(serializer.errors)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        task = self.find_task()
        if task is None:
            return not_found(kwargs.get('pk'))
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'], url_path='from-text')
    @idempotent
    def from_text(self, request):
        text = request.data.get('text') if isinstance(request.data, dict) else None
        if not isinstance(text, str) or not text.strip():
            return error_response(
                'VALIDATION_ERROR',
                'Validation failed',
                [{'field': 'text', 'issue': 'must be a non-empty string'}],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed = parse_task_text(text, timezone.localdate())
        except Exception:
            return error_response('PARSER_ERROR', 'The task text could not be parsed', [], status.HTTP_502_BAD_GATEWAY)
        if not isinstance(parsed, dict):
            return error_response(
                'INVALID_PARSER_OUTPUT',
                'The parser returned invalid data',
                [{'field': 'parser', 'issue': 'must return a dictionary'}],
                status.HTTP_502_BAD_GATEWAY,
            )
        recurrence = parsed.get('recurrence')
        if recurrence not in RECURRENCE_VALUES:
            return error_response(
                'INVALID_PARSER_OUTPUT',
                'The parser returned invalid data',
                [{'field': 'recurrence', 'issue': 'must be daily, weekly, monthly, yearly or null'}],
                status.HTTP_502_BAD_GATEWAY,
            )
        serializer = self.get_serializer(data={
            'title': parsed.get('title'),
            'description': parsed.get('description'),
            'due_date': parsed.get('due_date'),
        })
        if not serializer.is_valid():
            return validation_error(
                serializer.errors,
                status=status.HTTP_502_BAD_GATEWAY,
                code='INVALID_PARSER_OUTPUT',
                message='The parser returned invalid data',
            )
        serializer.save()
        return Response({**serializer.data, 'recurrence': recurrence}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'])
    def subtasks(self, request, pk=None):
        task = self.find_task()
        if task is None:
            return not_found(pk)
        if request.method == 'GET':
            serializer = self.get_serializer(task.subtasks.order_by('created_at', 'id'), many=True)
            return Response(serializer.data)
        if task.parent_id is not None:
            return subtask_not_allowed(task)
        if not isinstance(request.data, dict):
            return body_must_be_object()
        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data['parent'] = task.pk
        serializer = self.get_serializer(data=data)
        if not serializer.is_valid():
            return validation_error(serializer.errors)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    @idempotent
    def breakdown(self, request, pk=None):
        task = self.find_task()
        if task is None:
            return not_found(pk)
        if task.parent_id is not None:
            return subtask_not_allowed(task)
        try:
            items = break_down_task(task)
        except Exception:
            return error_response('BREAKDOWN_ERROR', 'The task could not be broken down', [], status.HTTP_502_BAD_GATEWAY)
        if not isinstance(items, list) or not items or not all(isinstance(item, dict) for item in items):
            return error_response(
                'INVALID_BREAKDOWN_OUTPUT',
                'The breakdown returned invalid data',
                [{'field': 'subtasks', 'issue': 'must be a non-empty list of objects'}],
                status.HTTP_502_BAD_GATEWAY,
            )
        payload = [
            {
                'title': item.get('title'),
                'description': item.get('description'),
                'due_date': item.get('due_date'),
                'priority': item.get('priority', task.priority),
                'parent': task.pk,
            }
            for item in items
        ]
        serializer = self.get_serializer(data=payload, many=True)
        if not serializer.is_valid():
            return validation_error(
                serializer.errors,
                status=status.HTTP_502_BAD_GATEWAY,
                code='INVALID_BREAKDOWN_OUTPUT',
                message='The breakdown returned invalid subtasks',
                prefix='subtasks',
            )
        with transaction.atomic():
            serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path=r'priority/(?P<level>[^/.]+)')
    def priority(self, request, level=None):
        if level not in PRIORITY_LEVELS:
            return error_response(
                'VALIDATION_ERROR',
                'Validation failed',
                [{'field': 'level', 'issue': 'must be one of low, medium, high'}],
                status.HTTP_400_BAD_REQUEST,
            )
        queryset = self.filter_queryset(self.get_queryset()).filter(priority=level)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)
