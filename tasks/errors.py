from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler


def error_response(code, message, details=None, status=400):
    return Response(
        {'error': {'code': str(code), 'message': str(message), 'details': details or []}},
        status=status,
    )


def errors_to_details(errors, prefix=''):
    fallback = prefix or api_settings.NON_FIELD_ERRORS_KEY
    details = []
    if isinstance(errors, dict):
        for field, value in errors.items():
            name = f'{prefix}.{field}' if prefix else str(field)
            details.extend(errors_to_details(value, name))
    elif isinstance(errors, list):
        for index, value in enumerate(errors):
            if isinstance(value, (dict, list)):
                details.extend(errors_to_details(value, f'{prefix}[{index}]'))
            else:
                details.append({'field': fallback, 'issue': str(value)})
    else:
        details.append({'field': fallback, 'issue': str(errors)})
    return details


def validation_error(errors, status=400, code='VALIDATION_ERROR', message='Validation failed', prefix=''):
    return error_response(code, message, errors_to_details(errors, prefix), status)


def not_found(pk):
    return error_response('NOT_FOUND', 'Task not found', [{'field': 'id', 'issue': f'no task with id {pk}'}], 404)


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    detail = getattr(exc, 'detail', None)
    if isinstance(exc, exceptions.ValidationError):
        code, message, details = 'VALIDATION_ERROR', 'Validation failed', errors_to_details(detail)
    elif isinstance(exc, (Http404, exceptions.NotFound)):
        code, message, details = 'NOT_FOUND', str(detail or 'Not found'), []
    else:
        code = str(getattr(exc, 'default_code', 'error')).upper()
        if isinstance(detail, (dict, list)):
            message, details = 'Request failed', errors_to_details(detail)
        else:
            message, details = str(detail or 'Request failed'), []
    response.data = {'error': {'code': code, 'message': message, 'details': details}}
    return response
