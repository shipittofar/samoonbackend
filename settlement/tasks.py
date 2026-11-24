from celery import shared_task


@shared_task
def run_settlement() -> dict:
    """Release finished hold periods; create weekly payout requests when the
    platform panel has them turned on."""
    from settlement.services import run_scheduled

    return run_scheduled()
