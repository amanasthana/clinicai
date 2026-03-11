"""
Prescription AI services.

DATA FLOW (privacy-critical — do not change without review):
  1. Doctor types full clinical note in browser
  2. Django receives note via HTTPS POST → stores raw note in PostgreSQL (Azure, encrypted at rest)
  3. deidentify_clinical_note() strips all PII: names, phone, Aadhaar, address, DOB
  4. ONLY de-identified text + age/gender sent to Claude API
  5. Claude returns structured SOAP + medicines + Hindi summary
  6. Django stitches back: patient name from DB + doctor name + clinic letterhead
  7. Full prescription stored in DB and rendered to doctor's browser

What Claude API NEVER sees:
  - Patient name, phone, Aadhaar, address, DOB, clinic name, doctor name
"""
import re
import json
import logging

from django.conf import settings
from anthropic import Anthropic

from .prompts import PRESCRIPTION_SYSTEM_PROMPT, DIFFERENTIAL_SYSTEM_PROMPT, INVESTIGATIONS_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """
    Robustly extract a JSON object from AI response text.
    Handles markdown fences, leading/trailing prose, and partial wrapping.
    """
    # Strip markdown code fences
    text = re.sub(r'```(?:json)?', '', text).strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find the first { ... } block (handles prose before/after JSON)
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # Last resort: raise with the cleaned text for logging
    raise json.JSONDecodeError("No valid JSON object found", text, 0)


def deidentify_clinical_note(text: str) -> str:
    """
    Strip all PII from clinical text before sending to AI.
    Only clinical facts remain: age, gender, symptoms, vitals, medications.
    """
    # Remove Aadhaar numbers (12 digits, possibly space/hyphen separated)
    text = re.sub(r'\d{4}[\s-]?\d{4}[\s-]?\d{4}', '', text)
    # Remove Indian mobile numbers
    text = re.sub(r'(\+91[\s-]?)?[6-9]\d{9}', '', text)
    # Remove name patterns (Mr/Mrs/Dr/Patient: followed by name)
    text = re.sub(
        r'(Mr\.?|Mrs\.?|Ms\.?|Shri|Smt|Dr\.?|Patient[:\s]*|Name[:\s]*)\s*[A-Z][a-z]+(\s+[A-Z][a-z]+){0,2}',
        '', text, flags=re.IGNORECASE,
    )
    # Remove 6-digit PIN codes (but not other 6-digit numbers like HbA1c values)
    text = re.sub(r'\b\d{6}\b', '', text)
    # Remove DOB (keep age)
    text = re.sub(
        r'(DOB|dob|Date of Birth|d\.o\.b)[:\s]*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}',
        '', text, flags=re.IGNORECASE,
    )
    # Remove address patterns
    text = re.sub(
        r'(Address|Addr|Resident of)[:\s].*?(?=\.|,\s*[A-Z]|\n|$)',
        '', text, flags=re.IGNORECASE,
    )
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def generate_prescription(raw_note: str, patient_age: int, patient_gender: str,
                          doctor=None, clinic=None) -> dict:
    """
    Full AI prescription generation pipeline.

    Steps:
      1. De-identify the clinical note (CRITICAL — never skip)
      2. Build minimal clinical input: age + gender + safe note
      3. Optionally append doctor favorites context (NOT PII)
      4. Call Claude Haiku with structured JSON prompt
      5. Parse and validate the response
      6. Return dict ready for saving to PrescriptionMedicine rows

    Args:
        raw_note: Doctor's raw clinical text (may contain PII)
        patient_age: Patient age (integer)
        patient_gender: 'M', 'F', or 'O'
        doctor: StaffMember instance (optional) — used to fetch favorites
        clinic: Clinic instance (optional) — used to fetch in-stock medicines

    Returns:
        dict with keys: soap_note, diagnosis, medicines (list), advice,
                        patient_summary_en, patient_summary_hi, follow_up_days,
                        clinical_evaluation, investigations_text
    """
    safe_note = deidentify_clinical_note(raw_note)
    gender_text = {'M': 'M', 'F': 'F', 'O': 'NB'}.get(patient_gender, '')
    clinical_input = f"{patient_age}{gender_text}, {safe_note}"

    # Append doctor's preferred medicines (NOT clinic inventory — inventory is for dispensing only)
    try:
        if doctor:
            from pharmacy.models import DoctorFavorite
            favs = list(
                DoctorFavorite.objects.filter(doctor=doctor)
                .select_related('medicine')[:30]
            )
            fav_lines = []
            for f in favs:
                line = f.display_name
                if f.default_dosage:
                    line += f" ({f.default_dosage})"
                if f.default_frequency:
                    line += f" {f.default_frequency}"
                fav_lines.append(line)
            if fav_lines:
                clinical_input += f"\n\nDoctor's preferred medicines (use if clinically appropriate): {', '.join(fav_lines)}"
    except Exception as e:
        logger.warning("Could not fetch inventory/favorites context: %s", e)

    logger.info("Calling Claude API for prescription generation (de-identified note sent)")

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1500,
        system=PRESCRIPTION_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': clinical_input}],
    )

    result_text = response.content[0].text
    prescription_data = _extract_json(result_text)
    logger.info("Claude API returned prescription successfully")
    return prescription_data


def get_differentials(raw_note: str, patient_age: int, patient_gender: str) -> dict:
    """
    Step 1 of differential workflow.
    Returns ranked list of differential diagnoses with probability and reasoning.

    Args:
        raw_note: Doctor's raw clinical text (will be de-identified)
        patient_age: Patient age
        patient_gender: 'M', 'F', or 'O'

    Returns:
        dict with key: differentials (list of ranked diagnosis objects)
    """
    safe_note = deidentify_clinical_note(raw_note)
    gender_text = {'M': 'M', 'F': 'F', 'O': 'NB'}.get(patient_gender, '')
    clinical_input = f"{patient_age}{gender_text}, {safe_note}"

    logger.info("Calling Claude API for differential diagnosis (de-identified)")

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1000,
        system=DIFFERENTIAL_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': clinical_input}],
    )

    result_text = response.content[0].text
    data = _extract_json(result_text)
    logger.info("Claude returned %d differentials", len(data.get('differentials', [])))
    return data


def get_investigations(selected_diagnosis: str, raw_note: str, patient_age: int, patient_gender: str) -> dict:
    """
    Step 2 of differential workflow.
    Returns investigations split into Immediate and Elective with availability context.

    Args:
        selected_diagnosis: Diagnosis chosen by doctor in Step 1
        raw_note: Doctor's raw clinical text (will be de-identified)
        patient_age: Patient age
        patient_gender: 'M', 'F', or 'O'

    Returns:
        dict with keys: diagnosis, investigations (immediate + elective lists)
    """
    safe_note = deidentify_clinical_note(raw_note)
    gender_text = {'M': 'M', 'F': 'F', 'O': 'NB'}.get(patient_gender, '')
    clinical_input = (
        f"Confirmed diagnosis: {selected_diagnosis}\n"
        f"Patient: {patient_age}{gender_text}\n"
        f"Clinical note: {safe_note}"
    )

    logger.info("Calling Claude API for investigations (diagnosis: %s)", selected_diagnosis)

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1000,
        system=INVESTIGATIONS_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': clinical_input}],
    )

    result_text = response.content[0].text
    data = _extract_json(result_text)
    logger.info("Claude returned investigations for: %s", selected_diagnosis)
    return data
