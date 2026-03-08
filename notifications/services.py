"""
Notification services stub.
WhatsApp integration is planned for Phase 3.
Do not send any patient data to external services until this is fully implemented.
"""
import logging

logger = logging.getLogger(__name__)


def send_whatsapp_reminder(patient_phone: str, message: str, visit_id=None) -> bool:
    """
    STUB: Send a WhatsApp message to a patient.
    Not yet implemented — placeholder for Phase 3 integration.

    Args:
        patient_phone: Patient's phone number (e.g., "9876543210")
        message: Message text to send
        visit_id: Optional visit UUID for logging

    Returns:
        False always (stub)
    """
    logger.info(
        "WhatsApp stub called for visit=%s — not yet implemented", visit_id
    )
    return False


def send_appointment_confirmation(patient_phone: str, token_number: int, clinic_name: str) -> bool:
    """STUB: Confirm appointment via WhatsApp."""
    message = (
        f"Your appointment at {clinic_name} is confirmed. "
        f"Token number: {token_number}. Please arrive on time."
    )
    return send_whatsapp_reminder(patient_phone, message)


def send_prescription_summary(patient_phone: str, summary_text: str, visit_id=None) -> bool:
    """STUB: Send prescription summary to patient via WhatsApp."""
    return send_whatsapp_reminder(patient_phone, summary_text, visit_id)
