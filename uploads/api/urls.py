from django.urls import path

from uploads.api.views import (
    UploadCancelAPIView,
    UploadCompleteAPIView,
    UploadDetailAPIView,
    UploadInitiateAPIView,
)

app_name = "uploads"

urlpatterns = [
    path("initiate/", UploadInitiateAPIView.as_view(), name="upload-initiate"),
    path("<uuid:asset_id>/complete/", UploadCompleteAPIView.as_view(), name="upload-complete"),
    path("<uuid:asset_id>/cancel/", UploadCancelAPIView.as_view(), name="upload-cancel"),
    path("<uuid:asset_id>/", UploadDetailAPIView.as_view(), name="upload-detail"),
]
