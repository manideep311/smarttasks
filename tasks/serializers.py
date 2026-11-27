import datetime
import re

from rest_framework import serializers

from .models import Task

DATE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}')

TEXT_ERRORS = {
    'required': 'is required',
    'null': 'must not be null',
    'blank': 'must not be empty',
    'invalid': 'must be a string',
    'max_length': 'must be at most {max_length} characters',
}


class StrictCharField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail('invalid')
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if not isinstance(data, bool):
            self.fail('invalid')
        return data


class StrictDateField(serializers.DateField):
    def to_internal_value(self, value):
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            return value
        if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
            self.fail('invalid')
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            self.fail('invalid')


class TaskSerializer(serializers.ModelSerializer):
    title = StrictCharField(max_length=200, error_messages=TEXT_ERRORS)
    description = StrictCharField(error_messages=TEXT_ERRORS)
    completed = StrictBooleanField(
        required=False,
        error_messages={'invalid': 'must be a boolean', 'null': 'must not be null'},
    )
    due_date = StrictDateField(
        required=False,
        allow_null=True,
        error_messages={'invalid': 'must be a real date in YYYY-MM-DD format'},
    )
    priority = serializers.ChoiceField(
        choices=Task.PRIORITY_CHOICES,
        required=False,
        error_messages={'invalid_choice': 'must be one of low, medium, high', 'null': 'must not be null'},
    )
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Task.objects.all(),
        required=False,
        allow_null=True,
        error_messages={'does_not_exist': 'task {pk_value} does not exist', 'incorrect_type': 'must be a task id'},
    )

    class Meta:
        model = Task
        fields = [
            'id',
            'title',
            'description',
            'completed',
            'due_date',
            'priority',
            'parent',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_parent(self, parent):
        if parent is None:
            return parent
        if self.instance is not None and parent.pk == self.instance.pk:
            raise serializers.ValidationError('a task cannot be its own parent')
        if parent.parent_id is not None:
            raise serializers.ValidationError('a subtask cannot have subtasks')
        return parent

    def validate(self, attrs):
        if attrs.get('parent') is not None and self.instance is not None and self.instance.subtasks.exists():
            raise serializers.ValidationError({'parent': 'a task with subtasks cannot become a subtask'})
        return attrs
