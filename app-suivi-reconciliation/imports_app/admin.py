from django.contrib import admin

from .models import ImportBatch, TransactionObservation

admin.site.register(ImportBatch)
admin.site.register(TransactionObservation)
