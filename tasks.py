from celery import shared_task
from Lockapi import tcr


@shared_task
def tcr_main(*args):
    tcr.main(*args)
