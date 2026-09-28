from utils.helpers import notify


def registration_notice(user):
    notify(user.id, "REGISTRATION", "Your NammaBiz account is ready.")


def request_notice(user_id, request_id):
    notify(user_id, "SERVICE_REQUEST", f"Service request #{request_id} was created.")


def job_notice(user_id, message):
    notify(user_id, "JOB_UPDATE", message)
