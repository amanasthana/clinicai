"""Tests for Hindi-only prescriptions: 100% Devanagari output, English digits only, privacy, caching, settings."""
import json
import re
from datetime import date, timedelta
from html.parser import HTMLParser
from unittest import mock
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, Client
from django.utils import timezone

from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role
from prescription.hindi import (
    HindiTranslationError, ensure_devanagari, get_hindi_content, hindi_date,
    hindi_whatsapp_message, to_ascii_digits, transliterate,
)
from prescription.models import Prescription, PrescriptionMedicine
from reception.models import Patient, Visit

LATIN = re.compile(r'[A-Za-z]')
DEVANAGARI_DIGIT = re.compile(r'[०-९]')


# ── helpers ────────────────────────────────────────────────────────────────

class _CardText(HTMLParser):
    """Collects the visible text inside the first .rx-card element (ignores tags/attributes)."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get('class') or ''
        if self.depth == 0 and tag == 'div' and 'rx-card' in cls.split():
            self.depth = 1
        elif self.depth and tag not in ('br', 'img', 'hr', 'input', 'meta', 'link'):
            self.depth += 1

    def handle_endtag(self, tag):
        if self.depth and tag not in ('br', 'img', 'hr', 'input', 'meta', 'link'):
            self.depth -= 1
            if self.depth == 0:
                self.depth = -1  # done — ignore the rest of the page

    def handle_data(self, data):
        if self.depth > 0:
            self.parts.append(data)


def card_text(html: str) -> str:
    p = _CardText()
    p.feed(html)
    return ' '.join(' '.join(p.parts).split())


def title_text(html: str) -> str:
    return re.search(r'<title>(.*?)</title>', html, re.S).group(1).strip()


def fake_claude(payload):
    """Stand-in for the Claude call: realistic Hindi, with deliberate slips the sanitiser must fix."""
    meds = []
    for m in payload['medicines']:
        name = m['drug_name']
        if 'Dolo' in name:
            meds.append({'drug_name': 'डोलो 650 mg गोली',        # stray Latin unit
                         'dosage': '1-0-1', 'frequency': 'खाने के बाद, दिन में दो बार',
                         'duration': '५ दिन',                       # Devanagari digit
                         'route': '', 'notes': 'बुखार के लिए'})
        else:
            meds.append({'drug_name': 'पैंटोप्राज़ोल 40 मि.ग्रा. गोली', 'dosage': '1-0-0',
                         'frequency': 'सुबह खाली पेट', 'duration': '14 दिन',
                         'route': 'मुँह से', 'notes': ''})
    out = {
        'diagnosis': 'वायरल बुखार' if payload['diagnosis'] else '',
        'complaint': '3 दिन से बुखार और बदन दर्द' if payload['complaint'] else '',
        'clinical_evaluation': 'गला लाल, CBC सामान्य' if payload['clinical_evaluation'] else '',
        'comorbidities': 'मधुमेह (शुगर)' if payload['comorbidities'] else '',
        'past_history': 'टाइफ़ाइड 2019 में' if payload['past_history'] else '',
        'drug_allergies': 'सल्फ़ा दवाएँ' if payload['drug_allergies'] else '',
        'investigations_text': 'सी.बी.सी., डेंगू NS1' if payload['investigations_text'] else '',
        'advice': 'खूब पानी पिएँ और आराम करें।' if payload['advice'] else '',
        'patient_summary': 'आपको वायरल बुखार है।' if payload['patient_summary'] else '',
        'medicines': meds,
    }
    return out


def make_rx(language='hi', **rx_overrides):
    clinic = Clinic.objects.create(
        name='City Health Clinic', address='Shop 12, Linking Road, Andheri West', city='Mumbai',
        state='Maharashtra', phone='9100000001',
    )
    user = User.objects.create_user(username='hindidoc', password='testpass')
    doctor = StaffMember.objects.create(
        clinic=clinic, user=user, role='doctor', display_name='Dr. Rajesh Sharma',
        qualification='MBBS, MD (Medicine)', registration_number='MMC-12345',
    )
    set_permissions_from_role(doctor)
    doctor.save()
    patient = Patient.objects.create(
        clinic=clinic, full_name='Ramesh Kumar Gupta', phone='9876543210', age=45, gender='M',
        blood_group='B+',
    )
    visit = Visit.objects.create(
        clinic=clinic, patient=patient, token_number=7, status='done',
        chief_complaint='Fever and body ache for 3 days',
        vitals_bp='130/85', vitals_temp='101.2', vitals_spo2='97%', vitals_weight='72 kg',
    )
    fields = dict(
        visit=visit, doctor=doctor, raw_clinical_note='Fever 3 days, body ache',
        diagnosis='Viral fever', advice='Drink plenty of fluids and rest.',
        patient_summary_en='You have a viral fever.', patient_summary_hi='',
        clinical_evaluation='Throat congested, CBC normal', comorbidities='Type 2 DM',
        past_history='Typhoid in 2019', drug_allergies='Sulfa drugs',
        investigations_text='CBC, Dengue NS1', follow_up_date=date(2026, 10, 9),
        validity_days=30, language=language,
    )
    fields.update(rx_overrides)
    rx = Prescription.objects.create(**fields)
    PrescriptionMedicine.objects.create(prescription=rx, drug_name='Tab Dolo 650mg', dosage='1-0-1',
                                        frequency='Twice daily after meals', duration='5 days',
                                        notes='For fever', order=0)
    PrescriptionMedicine.objects.create(prescription=rx, drug_name='Tab Pantoprazole 40mg', dosage='1-0-0',
                                        frequency='Empty stomach', duration='14 days', route='Oral', order=1)
    return rx, user


# ── unit: transliteration + formatting ────────────────────────────────────

class TransliterationTest(TestCase):

    def test_names_and_addresses_have_no_latin(self):
        samples = [
            'City Health Clinic', 'Dr. Rajesh Sharma', 'MBBS, MD (Medicine)', 'Ramesh Kumar Gupta',
            'Shop 12, Linking Road, Andheri West, Mumbai, Maharashtra', 'Priyanka Chopra',
            'Mohd. Irfan Khan', 'MMC-12345', 'B+', 'Xavier Quentin Zwick', 'Flat 3B, Sector 21',
        ]
        for s in samples:
            out = transliterate(s)
            self.assertFalse(LATIN.search(out), f'{s!r} → {out!r}')
            self.assertTrue(out.strip(), s)

    def test_known_spellings(self):
        self.assertEqual(transliterate('Dr. Rajesh Sharma'), 'डॉ. राजेश शर्मा')
        self.assertEqual(transliterate('City Health Clinic'), 'सिटी हेल्थ क्लिनिक')
        self.assertEqual(transliterate('MBBS, MD'), 'एम.बी.बी.एस., एम.डी.')
        self.assertEqual(transliterate('Andheri West, Mumbai'), 'अंधेरी पश्चिम, मुंबई')
        self.assertEqual(transliterate('Priyanka'), 'प्रियंका')
        self.assertEqual(transliterate('Vikram'), 'विक्रम')

    def test_digits_preserved_as_english(self):
        self.assertEqual(transliterate('Shop 12'), 'दुकान 12')
        self.assertEqual(transliterate('Tab Dolo 650mg'), 'गोली दोलो 650मि.ग्रा.')
        self.assertEqual(to_ascii_digits('५ दिन, १०-१४'), '5 दिन, 10-14')
        self.assertEqual(ensure_devanagari('१-०-१ SOS'), '1-0-1 ज़रूरत पड़ने पर')

    def test_no_word_is_not_treated_as_number_abbreviation(self):
        self.assertEqual(transliterate('House No. 5'), 'हाउस सं. 5')
        self.assertNotIn('सं.', transliterate('no fever'))

    def test_empty_values(self):
        self.assertEqual(transliterate(''), '')
        self.assertEqual(ensure_devanagari(None), '')

    def test_hindi_date(self):
        self.assertEqual(hindi_date(date(2026, 10, 4)), '04 अक्टूबर 2026')
        self.assertEqual(hindi_date(date(2026, 2, 28)), '28 फ़रवरी 2026')
        self.assertEqual(hindi_date(None), '')

    def test_existing_hindi_text_untouched(self):
        self.assertEqual(ensure_devanagari('खाने के बाद 2 बार'), 'खाने के बाद 2 बार')


# ── unit: AI translation pipeline ─────────────────────────────────────────

class HindiContentTest(TestCase):

    def setUp(self):
        self.rx, _ = make_rx()

    def test_privacy_no_names_or_phone_sent_to_ai(self):
        self.rx.visit.chief_complaint = 'Mr. Ramesh Gupta 9876543210 fever 3 days'
        self.rx.visit.save()
        with mock.patch('prescription.hindi._call_claude', side_effect=fake_claude) as m:
            get_hindi_content(self.rx)
        sent = json.dumps(m.call_args[0][0], ensure_ascii=False)
        for secret in ('Ramesh', 'Gupta', '9876543210', 'City Health', 'Rajesh', 'Sharma',
                       'Linking Road', 'Andheri', 'MMC-12345'):
            self.assertNotIn(secret, sent)
        self.assertIn('Viral fever', sent)
        self.assertIn('Dolo', sent)

    def test_output_sanitised_to_devanagari_and_ascii_digits(self):
        with mock.patch('prescription.hindi._call_claude', side_effect=fake_claude):
            data = get_hindi_content(self.rx)
        values = [v for k, v in data.items() if k != 'medicines']
        values += [v for m in data['medicines'] for v in m.values()]
        flat = ' '.join(values)
        self.assertFalse(LATIN.search(flat), flat)
        self.assertFalse(DEVANAGARI_DIGIT.search(flat), flat)
        self.assertEqual(data['medicines'][0]['duration'], '5 दिन')
        self.assertEqual(data['medicines'][0]['drug_name'], 'डोलो 650 मि.ग्रा. गोली')

    def test_translation_is_cached(self):
        with mock.patch('prescription.hindi._call_claude', side_effect=fake_claude) as m:
            get_hindi_content(self.rx)
            self.rx.refresh_from_db()
            get_hindi_content(self.rx)
        self.assertEqual(m.call_count, 1)

    def test_edit_invalidates_cache(self):
        with mock.patch('prescription.hindi._call_claude', side_effect=fake_claude) as m:
            get_hindi_content(self.rx)
            self.rx.advice = 'Steam inhalation twice daily.'
            self.rx.save()
            get_hindi_content(self.rx)
        self.assertEqual(m.call_count, 2)

    def test_medicine_count_mismatch_rejected(self):
        bad = lambda p: {**fake_claude(p), 'medicines': []}
        with mock.patch('prescription.hindi._call_claude', side_effect=bad):
            with self.assertRaises(HindiTranslationError):
                get_hindi_content(self.rx)
        self.rx.refresh_from_db()
        self.assertIsNone(self.rx.hindi_content)

    def test_api_failure_raises_translation_error(self):
        with mock.patch('prescription.hindi._call_claude', side_effect=RuntimeError('network down')):
            with self.assertRaises(HindiTranslationError):
                get_hindi_content(self.rx)

    def test_existing_hindi_summary_reused_not_retranslated(self):
        self.rx.patient_summary_hi = 'आपको वायरल बुखार है, 5 दिन दवा लें।'
        self.rx.save()
        with mock.patch('prescription.hindi._call_claude', side_effect=fake_claude) as m:
            get_hindi_content(self.rx)
        self.assertEqual(m.call_args[0][0]['patient_summary'], '')


# ── end-to-end: print / share views ───────────────────────────────────────

@mock.patch('prescription.hindi._call_claude', side_effect=fake_claude)
class HindiPrintViewTest(TestCase):

    def setUp(self):
        self.rx, user = make_rx()
        self.client = Client()
        self.client.login(username='hindidoc', password='testpass')

    def get_print(self, query=''):
        resp = self.client.get(f'/rx/print/{self.rx.id}/{query}')
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def assert_fully_hindi(self, html):
        text = card_text(html)
        self.assertTrue(text, 'card text empty')
        latin = LATIN.findall(text)
        self.assertFalse(latin, f'Latin letters on Hindi prescription: {text}')
        self.assertFalse(DEVANAGARI_DIGIT.search(text), f'Devanagari digits found: {text}')
        return text

    def test_hindi_prescription_is_100_percent_hindi(self, _m):
        html = self.get_print()
        text = self.assert_fully_hindi(html)
        for expected in [
            'सिटी हेल्थ क्लिनिक',                  # clinic name
            'दुकान 12, लिंकिंग रोड, अंधेरी पश्चिम, मुंबई, महाराष्ट्र',  # address
            'फ़ोन 9100000001',                       # phone digits stay English
            'डॉ. राजेश शर्मा',                     # doctor
            'एम.बी.बी.एस., एम.डी. (मेडिसिन)',      # qualification
            'पंजीकरण सं. एम.एम.सी.-12345',          # registration
            'रमेश कुमार गुप्ता',                    # patient
            '45 वर्ष', 'पुरुष', 'रक्त समूह बी+',
            'टोकन 7',
            'बी.पी. 130/85', 'तापमान 101.2°फ़ा', 'ऑक्सीजन 97%', 'वज़न 72 कि.ग्रा.',
            'वायरल बुखार',                          # diagnosis
            'डोलो 650 मि.ग्रा. गोली', '1-0-1', '5 दिन', '14 दिन',
            'सलाह', 'खूब पानी पिएँ',
            'अगली मुलाकात', '09 अक्टूबर 2026',
            'सुझाई गई जाँचें', 'आपके लिए',
            '30 दिनों के लिए मान्य',
        ]:
            self.assertIn(expected, text)
        today = timezone.now().date()
        self.assertIn(hindi_date(today), text)

    def test_page_language_and_title_are_hindi(self, _m):
        html = self.get_print()
        self.assertIn('<html lang="hi">', html)
        title = title_text(html)
        self.assertFalse(LATIN.search(title), title)   # browsers print the title in page headers
        self.assertIn('रमेश कुमार गुप्ता', title)

    def test_devanagari_font_loaded(self, _m):
        html = self.get_print()
        self.assertIn('family=Noto+Sans+Devanagari', html)
        self.assertIn("font-family: 'Noto Sans Devanagari'", html)

    def test_hindi_overrides_from_settings_used(self, _m):
        clinic = self.rx.visit.clinic
        clinic.name_hi = 'सिटी हेल्थ चिकित्सालय'
        clinic.address_hi = 'दुकान 12, लिंकिंग रोड, अंधेरी (प.), मुंबई'
        clinic.save()
        self.rx.doctor.display_name_hi = 'डॉ. राजेश शर्मा जी'
        self.rx.doctor.qualification_hi = 'एम.बी.बी.एस.'
        self.rx.doctor.save()
        patient = self.rx.visit.patient
        patient.name_hi = 'रमेश कुमार गुप्ता जी'
        patient.save()
        text = self.assert_fully_hindi(self.get_print())
        for expected in ('सिटी हेल्थ चिकित्सालय', 'अंधेरी (प.)', 'डॉ. राजेश शर्मा जी', 'रमेश कुमार गुप्ता जी'):
            self.assertIn(expected, text)

    def test_minimal_prescription_still_fully_hindi(self, _m):
        self.rx.clinical_evaluation = self.rx.comorbidities = self.rx.past_history = ''
        self.rx.drug_allergies = self.rx.investigations_text = self.rx.advice = ''
        self.rx.patient_summary_en = ''
        self.rx.follow_up_date = None
        self.rx.save()
        self.rx.medicines.all().delete()
        visit = self.rx.visit
        visit.vitals_bp = visit.vitals_temp = visit.vitals_spo2 = visit.vitals_weight = ''
        visit.save()
        self.rx.doctor.registration_number = ''
        self.rx.doctor.save()
        text = self.assert_fully_hindi(self.get_print())
        self.assertIn('कोई दवा नहीं लिखी गई।', text)

    def test_hide_remarks_setting_respected(self, _m):
        self.rx.doctor.show_rx_remarks = False
        self.rx.doctor.save()
        text = self.assert_fully_hindi(self.get_print())
        self.assertNotIn('बुखार के लिए', text)

    def test_lang_query_switches_to_english(self, _m):
        html = self.get_print('?lang=en')
        text = card_text(html)
        self.assertIn('City Health Clinic', text)
        self.assertIn('Tab Dolo 650mg', text)
        self.assertIn('href="?lang=hi"', html)

    def test_english_rx_can_be_viewed_in_hindi(self, _m):
        self.rx.language = 'en'
        self.rx.save()
        text = card_text(self.get_print())
        self.assertIn('City Health Clinic', text)
        self.assert_fully_hindi(self.get_print('?lang=hi'))

    def test_translation_failure_falls_back_to_english(self, m):
        m.side_effect = RuntimeError('API down')
        html = self.get_print()
        self.assertIn('Hindi translation is unavailable right now', html)
        self.assertIn('City Health Clinic', card_text(html))

    def test_public_share_link_is_hindi(self, _m):
        self.rx.share_token = __import__('uuid').uuid4()
        self.rx.save()
        anon = Client()
        resp = anon.get(f'/rx/share/{self.rx.share_token}/')
        self.assertEqual(resp.status_code, 200)
        self.assert_fully_hindi(resp.content.decode())

    def test_whatsapp_message_is_hindi(self, _m):
        self.rx.share_token = __import__('uuid').uuid4()
        self.rx.save()
        html = self.get_print()
        m = re.search(r"sendPdfWhatsApp\('([^']+)'\)", html)
        self.assertTrue(m, 'WhatsApp button missing')
        url = m.group(1).encode().decode('unicode_escape')
        text = unquote(url.split('?text=', 1)[1])
        without_link = re.sub(r'https?://\S+', '', text)
        self.assertFalse(LATIN.search(without_link), without_link)
        self.assertIn('नमस्ते रमेश कुमार गुप्ता जी', text)
        self.assertIn('09 अक्टूबर 2026', text)
        self.assertIn('?lang=hi', text)

    def test_english_rx_unchanged(self, m):
        self.rx.language = 'en'
        self.rx.save()
        html = self.get_print()
        self.assertIn('<html lang="en">', html)
        text = card_text(html)
        for expected in ('City Health Clinic', 'Dr. Rajesh Sharma', 'Ramesh Kumar Gupta', 'Viral fever',
                         'Tab Dolo 650mg', 'Twice daily after meals', 'Next Visit', 'Advice'):
            self.assertIn(expected, text)
        m.assert_not_called()


class HindiWhatsappMessageTest(TestCase):
    def test_message_without_follow_up(self):
        rx, _ = make_rx(follow_up_date=None)
        msg = hindi_whatsapp_message(rx, 'https://example.com/rx/share/abc/?lang=hi')
        self.assertNotIn('अगली मुलाकात', msg)
        self.assertFalse(LATIN.search(msg.replace('https://example.com/rx/share/abc/?lang=hi', '')))


# ── end-to-end: consult → save → print ────────────────────────────────────

class HindiSaveFlowTest(TestCase):

    def setUp(self):
        self.rx, user = make_rx()
        self.visit = self.rx.visit
        self.rx.delete()   # start from a fresh, unsaved consultation
        self.client = Client()
        self.client.login(username='hindidoc', password='testpass')

    def save(self, **extra):
        body = {
            'raw_clinical_note': 'Fever 3 days',
            'prescription': {
                'diagnosis': 'Viral fever', 'advice': 'Rest', 'medicines': [
                    {'drug_name': 'Tab Dolo 650mg', 'dosage': '1-0-1', 'frequency': 'Twice daily',
                     'duration': '5 days', 'notes': ''},
                ],
            },
            **extra,
        }
        resp = self.client.post(f'/rx/save/{self.visit.id}/', json.dumps(body), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_save_hindi_then_print_fully_hindi(self):
        data = self.save(language='hi', patient_name_hi='रमेश गुप्ता')
        rx = Prescription.objects.get(visit=self.visit)
        self.assertEqual(rx.language, 'hi')
        self.visit.patient.refresh_from_db()
        self.assertEqual(self.visit.patient.name_hi, 'रमेश गुप्ता')
        with mock.patch('prescription.hindi._call_claude', side_effect=fake_claude):
            html = self.client.get(data['print_url']).content.decode()
        text = card_text(html)
        self.assertFalse(LATIN.search(text), text)
        self.assertIn('रमेश गुप्ता', text)

    def test_latin_hindi_name_is_converted(self):
        self.save(language='hi', patient_name_hi='Ramesh Gupta')
        self.visit.patient.refresh_from_db()
        self.assertEqual(self.visit.patient.name_hi, 'रमेश गुप्ता')

    def test_default_language_is_english(self):
        self.save()
        self.assertEqual(Prescription.objects.get(visit=self.visit).language, 'en')

    def test_invalid_language_falls_back_to_english(self):
        self.save(language='fr')
        self.assertEqual(Prescription.objects.get(visit=self.visit).language, 'en')

    def test_english_save_does_not_touch_hindi_name(self):
        self.save(language='en', patient_name_hi='कुछ भी')
        self.visit.patient.refresh_from_db()
        self.assertEqual(self.visit.patient.name_hi, '')

    def test_consult_toggle_follows_doctor_setting(self):
        html = self.client.get(f'/rx/consult/{self.visit.id}/').content.decode()
        self.assertIn('id="rx-hindi-toggle"', html)
        self.assertNotRegex(html, r'id="rx-hindi-toggle"\s+checked')
        self.assertIn('value="रमेश कुमार गुप्ता"', html)   # suggested Hindi spelling
        doctor = StaffMember.objects.get(user__username='hindidoc')
        doctor.rx_language = 'hi'
        doctor.save()
        html = self.client.get(f'/rx/consult/{self.visit.id}/').content.decode()
        self.assertRegex(html, r'id="rx-hindi-toggle"\s+checked')

    def test_consult_toggle_follows_existing_rx_language(self):
        self.save(language='hi')
        html = self.client.get(f'/rx/consult/{self.visit.id}/').content.decode()
        self.assertRegex(html, r'id="rx-hindi-toggle"\s+checked')


# ── settings ──────────────────────────────────────────────────────────────

class HindiSettingsTest(TestCase):

    def setUp(self):
        self.clinic = Clinic.objects.create(name='City Health Clinic', city='Mumbai', state='Maharashtra')
        self.user = User.objects.create_user(username='hiadmin', password='testpass')
        self.sm = StaffMember.objects.create(clinic=self.clinic, user=self.user, role='admin',
                                             display_name='Dr. Aman Asthana', qualification='MBBS')
        set_permissions_from_role(self.sm)
        self.sm.save()
        self.client = Client()
        self.client.login(username='hiadmin', password='testpass')

    def test_clinic_edit_shows_suggestions_and_saves_hindi(self):
        html = self.client.get('/accounts/clinic/edit/').content.decode()
        self.assertIn('placeholder="सिटी हेल्थ क्लिनिक"', html)
        self.client.post('/accounts/clinic/edit/', {
            'name': 'City Health Clinic', 'city': 'Mumbai', 'state': 'Maharashtra',
            'name_hi': 'सिटी हेल्थ क्लिनिक', 'address_hi': 'मुंबई, महाराष्ट्र',
        })
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.name_hi, 'सिटी हेल्थ क्लिनिक')
        self.assertEqual(self.clinic.address_hi, 'मुंबई, महाराष्ट्र')

    def test_staff_edit_saves_rx_language_and_hindi_name(self):
        html = self.client.get(f'/accounts/staff/{self.sm.pk}/edit/').content.decode()
        self.assertIn('name="rx_language"', html)
        self.assertIn('placeholder="डॉ. अमन अस्थाना"', html)
        post = {
            'display_name': 'Dr. Aman Asthana', 'role': 'admin', 'qualification': 'MBBS',
            'rx_language': 'hi', 'display_name_hi': 'डॉ. अमन अस्थाना', 'qualification_hi': 'एम.बी.बी.एस.',
            'show_registration_on_rx': 'on',
        }
        from accounts.permissions import ALL_PERMISSION_FLAGS
        post.update({f: 'on' for f in ALL_PERMISSION_FLAGS})
        self.client.post(f'/accounts/staff/{self.sm.pk}/edit/', post)
        self.sm.refresh_from_db()
        self.assertEqual(self.sm.rx_language, 'hi')
        self.assertEqual(self.sm.display_name_hi, 'डॉ. अमन अस्थाना')
        self.assertEqual(self.sm.qualification_hi, 'एम.बी.बी.एस.')

    def test_preference_api_sets_rx_language(self):
        self.client.post('/accounts/api/preference/', json.dumps({'rx_language': 'hi'}),
                         content_type='application/json')
        self.sm.refresh_from_db()
        self.assertEqual(self.sm.rx_language, 'hi')
        self.client.post('/accounts/api/preference/', json.dumps({'rx_language': 'xx'}),
                         content_type='application/json')
        self.sm.refresh_from_db()
        self.assertEqual(self.sm.rx_language, 'hi')


class HindiMigrationIdempotencyTest(TestCase):
    """Re-running the migration SQL (partial re-deploy) must not fail."""

    def test_rerun_add_column_sql(self):
        import importlib
        mods = [
            importlib.import_module('accounts.migrations.0022_hindi_rx_fields'),
            importlib.import_module('reception.migrations.0006_patient_name_hi'),
            importlib.import_module('prescription.migrations.0009_prescription_language_hindi_content'),
        ]
        with connection.cursor() as cur:
            for mod in mods:
                cur.execute(mod.Migration.operations[0].sql)


class LocalInstructionTranslationTest(TestCase):
    """Common frequencies/durations use fixed Hindi so meaning is never dropped by the AI."""

    def test_frequency_dictionary(self):
        from prescription.hindi import local_frequency
        self.assertEqual(local_frequency('Twice daily after meals'), 'दिन में दो बार, खाने के बाद')
        self.assertEqual(local_frequency('twice daily, after meals'), 'दिन में दो बार, खाने के बाद')
        self.assertEqual(local_frequency('As needed for fever'), 'बुखार होने पर')
        self.assertEqual(local_frequency('BD'), 'दिन में दो बार')
        self.assertEqual(local_frequency('Something unusual'), '')

    def test_duration_patterns(self):
        from prescription.hindi import local_duration
        self.assertEqual(local_duration('5 days'), '5 दिन')
        self.assertEqual(local_duration('1 week'), '1 हफ़्ता')
        self.assertEqual(local_duration('2 weeks'), '2 हफ़्ते')
        self.assertEqual(local_duration('1 month'), '1 महीना')
        self.assertEqual(local_duration('3 Months'), '3 महीने')
        self.assertEqual(local_duration('5-7 days'), '5-7 दिन')
        self.assertEqual(local_duration('Lifelong'), 'आजीवन')
        self.assertEqual(local_duration('until review'), '')

    def test_dictionary_overrides_shortened_ai_output(self):
        rx, _ = make_rx()

        def lazy_ai(payload):
            out = fake_claude(payload)
            out['medicines'][0]['frequency'] = 'खाने के बाद'      # AI dropped "twice daily"
            return out

        with mock.patch('prescription.hindi._call_claude', side_effect=lazy_ai):
            data = get_hindi_content(rx)
        self.assertEqual(data['medicines'][0]['frequency'], 'दिन में दो बार, खाने के बाद')
        self.assertEqual(data['medicines'][0]['duration'], '5 दिन')
        self.assertEqual(data['medicines'][1]['frequency'], 'खाली पेट')

    def test_unknown_instruction_uses_ai_translation(self):
        rx, _ = make_rx()
        m = rx.medicines.get(order=1)
        m.frequency = 'Alternate days before breakfast'
        m.save()
        with mock.patch('prescription.hindi._call_claude', side_effect=fake_claude):
            data = get_hindi_content(rx)
        self.assertEqual(data['medicines'][1]['frequency'], 'सुबह खाली पेट')   # from the (fake) AI
