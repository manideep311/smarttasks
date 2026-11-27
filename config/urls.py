from django.contrib import admin
from django.urls import include, path, re_path

from tasks.views import api_not_found

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('tasks.urls')),
    re_path(r'^api/.*/$', api_not_found),
]
