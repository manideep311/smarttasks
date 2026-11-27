import json
from copy import deepcopy
from functools import wraps

from rest_framework.response import Response

from .errors import error_response

STORE = {}


def request_fingerprint(request):
    data = request.data
    if hasattr(data, 'dict'):
        data = data.dict()
    return json.dumps({'path': request.path, 'body': data}, sort_keys=True, default=str)


def idempotent(view_method):
    @wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        key = (request.headers.get('Idempotency-Key') or '').strip()
        if not key:
            return view_method(self, request, *args, **kwargs)
        body = request_fingerprint(request)
        saved = STORE.get(key)
        if saved is not None:
            if saved['body'] != body:
                return error_response(
                    'IDEMPOTENCY_KEY_REUSED',
                    'This Idempotency-Key was already used with a different request',
                    [{'field': 'Idempotency-Key', 'issue': 'already used with a different body'}],
                    422,
                )
            return Response(deepcopy(saved['response']['data']), status=saved['response']['status'])
        response = view_method(self, request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            STORE[key] = {
                'body': body,
                'response': {'status': response.status_code, 'data': deepcopy(response.data)},
            }
        return response

    return wrapper
