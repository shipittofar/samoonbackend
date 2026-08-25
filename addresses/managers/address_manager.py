from django.db import models


class ActiveAddressManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllAddressesManager(models.Manager):
    pass
