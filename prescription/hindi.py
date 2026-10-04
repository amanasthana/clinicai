"""
Hindi-only prescriptions.

Every string printed on a Hindi prescription is Devanagari; only the digits 0-9 stay English.

PRIVACY (same rules as services.py):
  - Names (patient, doctor, clinic) and the clinic address are NEVER sent to Claude.
    They are transliterated locally by transliterate(), or come from the Hindi
    override fields (Patient.name_hi, StaffMember.display_name_hi, Clinic.name_hi …).
  - Only clinical content (diagnosis, medicines, advice …) goes to Claude, after
    deidentify_clinical_note() on every free-text field.

The Claude translation is cached on Prescription.hindi_content together with a hash
of the source fields, so it is regenerated only when the prescription is edited.
"""
import hashlib
import json
import logging
import re

from django.conf import settings

from .prompts import HINDI_RX_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class HindiTranslationError(Exception):
    pass


# ── Digits ─────────────────────────────────────────────────────────────────
_DEVANAGARI_DIGITS = str.maketrans('०१२३४५६७८९', '0123456789')


def to_ascii_digits(text: str) -> str:
    return (text or '').translate(_DEVANAGARI_DIGITS)


# ── Local Roman → Devanagari transliteration ──────────────────────────────
# Used for names/addresses (never sent to the AI) and as a safety net for any
# Latin letters left in AI output. Doctors can correct names in settings.

_LETTER_NAMES = {
    'a': 'ए', 'b': 'बी', 'c': 'सी', 'd': 'डी', 'e': 'ई', 'f': 'एफ़', 'g': 'जी',
    'h': 'एच', 'i': 'आई', 'j': 'जे', 'k': 'के', 'l': 'एल', 'm': 'एम', 'n': 'एन',
    'o': 'ओ', 'p': 'पी', 'q': 'क्यू', 'r': 'आर', 's': 'एस', 't': 'टी', 'u': 'यू',
    'v': 'वी', 'w': 'डब्ल्यू', 'x': 'एक्स', 'y': 'वाई', 'z': 'ज़ेड',
}

# Honorifics: the trailing "." in the source is consumed.
_HONORIFICS = {
    'dr': 'डॉ.', 'mr': 'श्री', 'mrs': 'श्रीमती', 'ms': 'सुश्री', 'smt': 'श्रीमती',
    'shri': 'श्री', 'sri': 'श्री', 'no': 'सं.', 'opp': 'सामने',
}

_WORDS = {
    # units / dosage forms
    'mg': 'मि.ग्रा.', 'ml': 'मि.ली.', 'mcg': 'माइक्रोग्राम', 'g': 'ग्राम', 'gm': 'ग्राम',
    'kg': 'कि.ग्रा.', 'kgs': 'कि.ग्रा.', 'iu': 'आई.यू.', 'cm': 'से.मी.', 'mm': 'मि.मी.',
    'tab': 'गोली', 'tabs': 'गोली', 'tablet': 'गोली', 'tablets': 'गोली',
    'cap': 'कैप्सूल', 'caps': 'कैप्सूल', 'capsule': 'कैप्सूल', 'syp': 'सिरप', 'syrup': 'सिरप',
    'inj': 'इंजेक्शन', 'injection': 'इंजेक्शन', 'oint': 'मलहम', 'ointment': 'मलहम',
    'cream': 'क्रीम', 'gel': 'जेल', 'drops': 'ड्रॉप्स', 'drop': 'ड्रॉप', 'sos': 'ज़रूरत पड़ने पर',
    'iv': 'नस में', 'im': 'मांसपेशी में', 'sc': 'त्वचा के नीचे',
    'yrs': 'वर्ष', 'yr': 'वर्ष', 'years': 'वर्ष', 'days': 'दिन', 'day': 'दिन',
    # address / clinic words
    'clinic': 'क्लिनिक', 'hospital': 'अस्पताल', 'health': 'हेल्थ', 'care': 'केयर',
    'city': 'सिटी', 'medical': 'मेडिकल', 'centre': 'सेंटर', 'center': 'सेंटर',
    'nursing': 'नर्सिंग', 'home': 'होम', 'polyclinic': 'पॉलीक्लिनिक', 'diagnostic': 'डायग्नोस्टिक',
    'diagnostics': 'डायग्नोस्टिक्स', 'family': 'फैमिली', 'child': 'चाइल्ड', 'multispeciality': 'मल्टीस्पेशलिटी',
    'road': 'रोड', 'rd': 'रोड', 'street': 'स्ट्रीट', 'st': 'स्ट्रीट', 'lane': 'लेन', 'marg': 'मार्ग',
    'nagar': 'नगर', 'colony': 'कॉलोनी', 'sector': 'सेक्टर', 'near': 'निकट', 'opposite': 'सामने',
    'west': 'पश्चिम', 'east': 'पूर्व', 'north': 'उत्तर', 'south': 'दक्षिण', 'floor': 'मंज़िल',
    'shop': 'दुकान', 'building': 'बिल्डिंग', 'tower': 'टॉवर', 'plaza': 'प्लाज़ा', 'market': 'मार्केट',
    'main': 'मेन', 'cross': 'क्रॉस', 'station': 'स्टेशन', 'complex': 'कॉम्प्लेक्स', 'society': 'सोसाइटी',
    'apartment': 'अपार्टमेंट', 'chowk': 'चौक', 'bazar': 'बाज़ार', 'bazaar': 'बाज़ार', 'gali': 'गली',
    'the': 'द', 'and': 'एंड', 'of': 'ऑफ़', 'new': 'नई', 'old': 'पुराना',
    'house': 'हाउस', 'plot': 'प्लॉट', 'flat': 'फ़्लैट', 'block': 'ब्लॉक', 'phase': 'फ़ेज़',
    'gate': 'गेट', 'park': 'पार्क', 'garden': 'गार्डन', 'hills': 'हिल्स', 'enclave': 'एन्क्लेव',
    'vihar': 'विहार', 'puram': 'पुरम', 'ganj': 'गंज', 'pur': 'पुर', 'bagh': 'बाग़',
    'bus': 'बस', 'stand': 'स्टैंड', 'stop': 'स्टॉप', 'depot': 'डिपो', 'railway': 'रेलवे',
    'metro': 'मेट्रो', 'highway': 'हाईवे', 'bypass': 'बाईपास', 'temple': 'मंदिर', 'mandir': 'मंदिर',
    'masjid': 'मस्जिद', 'church': 'चर्च', 'school': 'स्कूल', 'college': 'कॉलेज', 'bank': 'बैंक',
    'post': 'पोस्ट', 'office': 'ऑफ़िस', 'police': 'पुलिस', 'chowki': 'चौकी', 'petrol': 'पेट्रोल',
    'pump': 'पंप', 'village': 'गाँव', 'district': 'ज़िला', 'dist': 'ज़िला', 'tehsil': 'तहसील',
    'circle': 'सर्कल', 'square': 'स्क्वेयर', 'mall': 'मॉल', 'hotel': 'होटल', 'cinema': 'सिनेमा',
    'gandhi': 'गांधी', 'nehru': 'नेहरू', 'subhash': 'सुभाष', 'tilak': 'तिलक', 'shivaji': 'शिवाजी',
    'ambedkar': 'अंबेडकर', 'rajiv': 'राजीव', 'indira': 'इंदिरा', 'netaji': 'नेताजी', 'azad': 'आज़ाद',
    'sadar': 'सदर', 'civil': 'सिविल', 'lines': 'लाइंस', 'cantt': 'कैंट', 'industrial': 'इंडस्ट्रियल',
    'area': 'एरिया', 'estate': 'एस्टेट', 'layout': 'लेआउट', 'extension': 'एक्सटेंशन',
    # qualifications / specialities
    'medicine': 'मेडिसिन', 'general': 'जनरल', 'physician': 'फ़िज़िशियन', 'consultant': 'कंसल्टेंट',
    'specialist': 'विशेषज्ञ', 'surgeon': 'सर्जन', 'surgery': 'सर्जरी', 'paediatrics': 'बाल रोग',
    'pediatrics': 'बाल रोग', 'paediatrician': 'बाल रोग विशेषज्ञ', 'pediatrician': 'बाल रोग विशेषज्ञ',
    'gynaecology': 'स्त्री रोग', 'gynecology': 'स्त्री रोग', 'gynaecologist': 'स्त्री रोग विशेषज्ञ',
    'gynecologist': 'स्त्री रोग विशेषज्ञ', 'obstetrics': 'प्रसूति', 'dental': 'डेंटल',
    'dentist': 'दंत चिकित्सक', 'orthopaedics': 'हड्डी रोग', 'orthopedics': 'हड्डी रोग',
    'dermatology': 'त्वचा रोग', 'cardiology': 'हृदय रोग', 'ent': 'नाक-कान-गला',
    'diabetologist': 'मधुमेह विशेषज्ञ', 'gold': 'स्वर्ण', 'medalist': 'पदक विजेता',
    'mohd': 'मोहम्मद', 'mohammad': 'मोहम्मद', 'mohammed': 'मोहम्मद', 'muhammad': 'मोहम्मद',
    'anand': 'आनंद', 'prakash': 'प्रकाश', 'kishore': 'किशोर', 'kishor': 'किशोर',
    'swati': 'स्वाति', 'bhavna': 'भावना', 'irfan': 'इरफ़ान', 'shetty': 'शेट्टी',
    # places
    'india': 'भारत', 'mumbai': 'मुंबई', 'delhi': 'दिल्ली', 'pune': 'पुणे', 'thane': 'ठाणे',
    'andheri': 'अंधेरी', 'bandra': 'बांद्रा', 'dadar': 'दादर', 'borivali': 'बोरीवली',
    'kolkata': 'कोलकाता', 'chennai': 'चेन्नई', 'bangalore': 'बेंगलुरु', 'bengaluru': 'बेंगलुरु',
    'hyderabad': 'हैदराबाद', 'ahmedabad': 'अहमदाबाद', 'lucknow': 'लखनऊ', 'kanpur': 'कानपुर',
    'jaipur': 'जयपुर', 'patna': 'पटना', 'indore': 'इंदौर', 'bhopal': 'भोपाल', 'noida': 'नोएडा',
    'gurgaon': 'गुड़गांव', 'gurugram': 'गुरुग्राम', 'nagpur': 'नागपुर', 'nashik': 'नासिक',
    'varanasi': 'वाराणसी', 'agra': 'आगरा', 'allahabad': 'इलाहाबाद', 'prayagraj': 'प्रयागराज',
    'ghaziabad': 'गाज़ियाबाद', 'faridabad': 'फ़रीदाबाद', 'meerut': 'मेरठ', 'surat': 'सूरत',
    'chandigarh': 'चंडीगढ़', 'dehradun': 'देहरादून', 'ranchi': 'रांची', 'raipur': 'रायपुर',
    'maharashtra': 'महाराष्ट्र', 'uttar': 'उत्तर', 'pradesh': 'प्रदेश', 'madhya': 'मध्य',
    'bihar': 'बिहार', 'rajasthan': 'राजस्थान', 'gujarat': 'गुजरात', 'karnataka': 'कर्नाटक',
    'haryana': 'हरियाणा', 'punjab': 'पंजाब', 'uttarakhand': 'उत्तराखंड', 'jharkhand': 'झारखंड',
    'chhattisgarh': 'छत्तीसगढ़', 'odisha': 'ओडिशा', 'telangana': 'तेलंगाना', 'tamil': 'तमिल',
    'nadu': 'नाडु', 'kerala': 'केरल', 'bengal': 'बंगाल', 'goa': 'गोवा', 'assam': 'असम',
    'himachal': 'हिमाचल', 'andhra': 'आंध्र',
    # common name parts
    'kumar': 'कुमार', 'kumari': 'कुमारी', 'devi': 'देवी', 'singh': 'सिंह', 'sharma': 'शर्मा',
    'verma': 'वर्मा', 'gupta': 'गुप्ता', 'patel': 'पटेल', 'yadav': 'यादव', 'mishra': 'मिश्रा',
    'pandey': 'पांडे', 'tiwari': 'तिवारी', 'shukla': 'शुक्ला', 'agarwal': 'अग्रवाल',
    'aggarwal': 'अग्रवाल', 'jain': 'जैन', 'khan': 'ख़ान', 'ram': 'राम', 'lal': 'लाल',
    'prasad': 'प्रसाद', 'chandra': 'चंद्र', 'mehta': 'मेहता', 'joshi': 'जोशी', 'reddy': 'रेड्डी',
    'rao': 'राव', 'nair': 'नायर', 'iyer': 'अय्यर', 'das': 'दास', 'roy': 'रॉय', 'sinha': 'सिन्हा',
    'srivastava': 'श्रीवास्तव', 'chauhan': 'चौहान', 'thakur': 'ठाकुर', 'kapoor': 'कपूर',
    'khanna': 'खन्ना', 'malhotra': 'मल्होत्रा', 'arora': 'अरोड़ा', 'bansal': 'बंसल',
    'goyal': 'गोयल', 'saxena': 'सक्सेना', 'dubey': 'दुबे', 'tripathi': 'त्रिपाठी',
    'chaudhary': 'चौधरी', 'choudhary': 'चौधरी', 'rani': 'रानी', 'asthana': 'अस्थाना',
    'rajesh': 'राजेश', 'ramesh': 'रमेश', 'suresh': 'सुरेश', 'mahesh': 'महेश', 'mukesh': 'मुकेश',
    'dinesh': 'दिनेश', 'rakesh': 'राकेश', 'ganesh': 'गणेश', 'mohan': 'मोहन', 'shyam': 'श्याम',
    'aman': 'अमन', 'amit': 'अमित', 'sumit': 'सुमित', 'ravi': 'रवि', 'rahul': 'राहुल',
    'rohit': 'रोहित', 'vikas': 'विकास', 'manoj': 'मनोज', 'anil': 'अनिल', 'sunil': 'सुनील',
    'deepak': 'दीपक', 'vijay': 'विजय', 'ajay': 'अजय', 'sanjay': 'संजय', 'arun': 'अरुण',
    'priya': 'प्रिया', 'sunita': 'सुनीता', 'anita': 'अनीता', 'geeta': 'गीता', 'gita': 'गीता',
    'sita': 'सीता', 'pooja': 'पूजा', 'puja': 'पूजा', 'neha': 'नेहा', 'anjali': 'अंजलि',
    'kavita': 'कविता', 'rekha': 'रेखा', 'meena': 'मीना', 'seema': 'सीमा', 'lakshmi': 'लक्ष्मी',
    'radha': 'राधा', 'krishna': 'कृष्ण', 'baby': 'बेबी', 'master': 'मास्टर',
}

_VOWELS = [  # (roman, independent, matra) — longest first
    ('aa', 'आ', 'ा'), ('ai', 'ऐ', 'ै'), ('au', 'औ', 'ौ'), ('ee', 'ई', 'ी'), ('ii', 'ई', 'ी'),
    ('oo', 'ऊ', 'ू'), ('ou', 'औ', 'ौ'), ('ei', 'ए', 'े'), ('ey', 'ए', 'े'),
    ('a', 'अ', ''), ('e', 'ए', 'े'), ('i', 'इ', 'ि'), ('o', 'ओ', 'ो'), ('u', 'उ', 'ु'),
]
_CONSONANTS = [  # longest first
    ('chh', 'छ'), ('ksh', 'क्ष'), ('kh', 'ख'), ('gh', 'घ'), ('ch', 'च'), ('jh', 'झ'),
    ('th', 'थ'), ('dh', 'ध'), ('ph', 'फ'), ('bh', 'भ'), ('sh', 'श'), ('ck', 'क'),
    ('k', 'क'), ('g', 'ग'), ('j', 'ज'), ('t', 'त'), ('d', 'द'), ('n', 'न'), ('p', 'प'),
    ('b', 'ब'), ('m', 'म'), ('y', 'य'), ('r', 'र'), ('l', 'ल'), ('v', 'व'), ('w', 'व'),
    ('s', 'स'), ('h', 'ह'), ('f', 'फ़'), ('z', 'ज़'), ('q', 'क'), ('x', 'क्स'),
]
_HALANT = '्'
_ANUSVARA = 'ं'


def _match(word, i, table):
    for roman, *rest in table:
        if word.startswith(roman, i):
            return roman, rest
    return None, None


def _phonetic(word: str) -> str:
    """Phonetic transliteration of one lowercase Latin word."""
    out = []
    prev_cons = False
    i, n = 0, len(word)
    while i < n:
        ch = word[i]
        if ch == 'c':  # soft c before e/i/y
            roman, rest = ('c', ['स']) if word[i + 1:i + 2] in ('e', 'i', 'y') else ('c', ['क'])
            if word.startswith('ch', i) or word.startswith('ck', i):
                roman, rest = _match(word, i, _CONSONANTS)
        else:
            roman, rest = _match(word, i, _VOWELS)
            if roman:
                indep, matra = rest
                at_end = i + len(roman) == n
                if prev_cons:
                    if roman == 'a' and at_end and n > 2:
                        matra = 'ा'          # Sharma → शर्मा
                    elif roman == 'i' and at_end:
                        matra = 'ी'
                    out.append(matra)
                else:
                    out.append(indep)
                prev_cons = False
                i += len(roman)
                continue
            if ch == 'y' and prev_cons and i == n - 1:   # final y after consonant → ी
                out.append('ी')
                i += 1
                continue
            roman, rest = _match(word, i, _CONSONANTS)
        if not roman:
            i += 1
            continue
        nxt = word[i + len(roman):i + len(roman) + 1]
        if roman in ('n', 'm') and not prev_cons and out and nxt and nxt not in 'aeiouy' \
                and word[i + len(roman):i + len(roman) + 1] != roman:
            out.append(_ANUSVARA)                 # Ganga → गंगा
            prev_cons = False
            i += len(roman)
            continue
        if prev_cons:
            out.append(_HALANT)
        out.append(rest[0])
        prev_cons = True
        i += len(roman)
    return ''.join(out)


def _transliterate_word(word: str) -> str:
    low = word.lower()
    if low in _WORDS:
        return _WORDS[low]
    # Acronyms (MBBS, MD, BP) and single capital letters are spelled out
    if word.isupper() and len(word) <= 6:
        letters = [_LETTER_NAMES[c] for c in low]
        return letters[0] if len(letters) == 1 else '.'.join(letters) + '.'
    return _phonetic(low)


_LATIN_RUN = re.compile(r'([A-Za-z]+)(\.?)')


def transliterate(text: str) -> str:
    """Replace every Latin word in text with Devanagari; leave everything else intact."""
    if not text:
        return ''

    def repl(m):
        word, dot = m.group(1), m.group(2)
        low = word.lower()
        if low in _HONORIFICS and (dot or low != 'no'):
            return _HONORIFICS[low]          # "Dr." → "डॉ." (honorific carries its own dot)
        out = _phonetic(low) if low == 'no' else _transliterate_word(word)
        if dot and out.endswith('.'):
            return out                       # "MBBS." → avoid double dot
        return out + dot

    return to_ascii_digits(_LATIN_RUN.sub(repl, text))


def ensure_devanagari(text: str) -> str:
    """Final guarantee: no Latin letters, only ASCII digits."""
    return transliterate(to_ascii_digits(text or '')).strip()


# ── Fixed labels / formatting ──────────────────────────────────────────────
HI_MONTHS = ['जनवरी', 'फ़रवरी', 'मार्च', 'अप्रैल', 'मई', 'जून', 'जुलाई',
             'अगस्त', 'सितंबर', 'अक्टूबर', 'नवंबर', 'दिसंबर']
HI_GENDER = {'M': 'पुरुष', 'F': 'महिला', 'O': 'अन्य'}


def hindi_date(d) -> str:
    if not d:
        return ''
    return f'{d.day:02d} {HI_MONTHS[d.month - 1]} {d.year}'


def blood_group_hi(bg: str) -> str:
    return transliterate((bg or '').upper())


def vitals_hi(visit) -> str:
    parts = []
    if visit.vitals_bp:
        parts.append(f'बी.पी. {ensure_devanagari(visit.vitals_bp)}')
    if visit.vitals_temp:
        parts.append(f'तापमान {ensure_devanagari(visit.vitals_temp)}°फ़ा')
    if visit.vitals_spo2:
        parts.append(f'ऑक्सीजन {ensure_devanagari(visit.vitals_spo2)}')
    if visit.vitals_weight:
        parts.append(f'वज़न {ensure_devanagari(visit.vitals_weight)}')
    return ' · '.join(parts)


def patient_name_hi(patient) -> str:
    return ensure_devanagari(patient.name_hi) if patient.name_hi else transliterate(patient.full_name)


def doctor_name_hi(doctor) -> str:
    return ensure_devanagari(doctor.display_name_hi) if doctor.display_name_hi else transliterate(doctor.display_name)


def doctor_qualification_hi(doctor) -> str:
    return ensure_devanagari(doctor.qualification_hi) if doctor.qualification_hi else transliterate(doctor.qualification)


def clinic_name_hi(clinic) -> str:
    return ensure_devanagari(clinic.name_hi) if clinic.name_hi else transliterate(clinic.name)


def clinic_address_hi(clinic) -> str:
    """Full address line (address, city, state) in Hindi — phone digits appended by the template."""
    if clinic.address_hi:
        return ensure_devanagari(clinic.address_hi)
    parts = [p for p in (clinic.address, clinic.city, clinic.state) if p]
    return transliterate(', '.join(parts))


# ── Fixed translations for common medicine instructions ───────────────────
# Deterministic, so the same instruction always prints the same Hindi, and nothing
# is dropped (the AI tends to shorten "Twice daily after meals" when dosage is 1-0-1).
HI_FREQUENCY = {
    'once daily': 'रोज़ एक बार', 'once a day': 'रोज़ एक बार', 'od': 'रोज़ एक बार',
    'once daily in morning': 'रोज़ सुबह एक बार', 'once daily morning': 'रोज़ सुबह एक बार',
    'once daily in the morning': 'रोज़ सुबह एक बार',
    'once daily at night': 'रोज़ रात में एक बार', 'once daily at bedtime': 'रोज़ रात को सोते समय',
    'once daily before bed': 'रोज़ रात को सोते समय', 'at bedtime': 'रात को सोते समय', 'hs': 'रात को सोते समय',
    'once daily after meals': 'रोज़ एक बार, खाने के बाद', 'once daily before breakfast': 'रोज़ एक बार, नाश्ते से पहले',
    'twice daily': 'दिन में दो बार', 'twice a day': 'दिन में दो बार', 'bd': 'दिन में दो बार', 'bid': 'दिन में दो बार',
    'twice daily after meals': 'दिन में दो बार, खाने के बाद', 'twice daily after food': 'दिन में दो बार, खाने के बाद',
    'twice daily before meals': 'दिन में दो बार, खाने से पहले', 'twice daily with food': 'दिन में दो बार, खाने के साथ',
    'thrice daily': 'दिन में तीन बार', 'three times daily': 'दिन में तीन बार', 'three times a day': 'दिन में तीन बार',
    '3 times daily': 'दिन में 3 बार', 'tds': 'दिन में तीन बार', 'tid': 'दिन में तीन बार',
    'thrice daily after meals': 'दिन में तीन बार, खाने के बाद', 'thrice daily after food': 'दिन में तीन बार, खाने के बाद',
    'thrice daily before meals': 'दिन में तीन बार, खाने से पहले', 'thrice daily with water': 'दिन में तीन बार, पानी के साथ',
    'four times daily': 'दिन में 4 बार', '4 times daily': 'दिन में 4 बार', 'qid': 'दिन में 4 बार',
    'every 4 hours': 'हर 4 घंटे पर', 'every 6 hours': 'हर 6 घंटे पर', 'every 8 hours': 'हर 8 घंटे पर',
    'every 12 hours': 'हर 12 घंटे पर',
    'after meals': 'खाने के बाद', 'after food': 'खाने के बाद', 'before meals': 'खाने से पहले',
    'before food': 'खाने से पहले', 'with food': 'खाने के साथ', 'with meals': 'खाने के साथ',
    '30 min before food': 'खाने से 30 मिनट पहले', '30 minutes before food': 'खाने से 30 मिनट पहले',
    'empty stomach': 'खाली पेट', 'with milk': 'दूध के साथ',
    'sos': 'ज़रूरत पड़ने पर', 'sos/as needed': 'ज़रूरत पड़ने पर', 'as needed': 'ज़रूरत पड़ने पर',
    'as needed for fever': 'बुखार होने पर', 'as needed for pain': 'दर्द होने पर', 'sos for fever': 'बुखार होने पर',
    'sos for pain': 'दर्द होने पर', 'once': 'एक बार', 'stat': 'तुरंत एक बार',
    'once weekly': 'हफ़्ते में एक बार', 'once a week': 'हफ़्ते में एक बार',
    'apply locally': 'प्रभावित जगह पर लगाएँ', 'apply twice daily': 'दिन में दो बार लगाएँ',
    'apply once daily': 'दिन में एक बार लगाएँ', 'apply thrice daily': 'दिन में तीन बार लगाएँ',
    'sip throughout the day': 'दिन भर घूँट-घूँट पिएँ', 'sip slowly throughout the day': 'दिन भर धीरे-धीरे पिएँ',
}
HI_DURATION_WORDS = {
    'lifelong': 'आजीवन', 'ongoing': 'जारी रखें', 'continue': 'जारी रखें', 'till better': 'ठीक होने तक',
    'till symptoms resolve': 'लक्षण ठीक होने तक', 'as needed': 'ज़रूरत के अनुसार', 'sos': 'ज़रूरत के अनुसार',
    'single dose': 'एक खुराक', 'once': 'एक बार',
}
_DURATION_UNITS = {
    'day': ('दिन', 'दिन'), 'days': ('दिन', 'दिन'), 'd': ('दिन', 'दिन'),
    'week': ('हफ़्ता', 'हफ़्ते'), 'weeks': ('हफ़्ता', 'हफ़्ते'), 'wk': ('हफ़्ता', 'हफ़्ते'), 'wks': ('हफ़्ता', 'हफ़्ते'),
    'month': ('महीना', 'महीने'), 'months': ('महीना', 'महीने'), 'mo': ('महीना', 'महीने'),
}
_DURATION_RE = re.compile(r'^\s*(\d+(?:\s*-\s*\d+)?)\s*([a-z]+)\.?\s*$', re.I)


def local_frequency(text: str) -> str:
    key = ' '.join((text or '').lower().replace(',', ' ').split())
    return HI_FREQUENCY.get(key, '')


def local_duration(text: str) -> str:
    key = ' '.join((text or '').lower().split())
    if key in HI_DURATION_WORDS:
        return HI_DURATION_WORDS[key]
    m = _DURATION_RE.match(key)
    if m and m.group(2) in _DURATION_UNITS:
        num = re.sub(r'\s+', '', m.group(1))
        singular, plural = _DURATION_UNITS[m.group(2)]
        return f'{num} {singular if num == "1" else plural}'
    return ''


# ── AI translation of clinical content ────────────────────────────────────

def _source_payload(rx) -> dict:
    """Clinical fields to translate. Free text is de-identified; no names are included."""
    from .services import deidentify_clinical_note

    visit = rx.visit
    complaint = (visit.chief_complaint or rx.raw_clinical_note or '')[:200]
    payload = {
        'diagnosis': rx.diagnosis,
        'complaint': complaint,
        'clinical_evaluation': rx.clinical_evaluation,
        'comorbidities': rx.comorbidities,
        'past_history': rx.past_history,
        'drug_allergies': rx.drug_allergies,
        'investigations_text': rx.investigations_text,
        'advice': rx.advice,
        # Existing Hindi summary is reused; only translate English when Hindi is missing
        'patient_summary': '' if rx.patient_summary_hi else rx.patient_summary_en,
    }
    payload = {k: deidentify_clinical_note(v) if v else '' for k, v in payload.items()}
    payload['medicines'] = [
        {
            'drug_name': m.drug_name, 'dosage': m.dosage, 'frequency': m.frequency,
            'duration': m.duration, 'route': m.route, 'notes': m.notes,
        }
        for m in rx.medicines.all()
    ]
    return payload


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _call_claude(payload: dict) -> dict:
    from anthropic import Anthropic
    from .services import _extract_json

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=4000,
        system=HINDI_RX_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
    )
    return _extract_json(response.content[0].text)


def _sanitize(source: dict, translated: dict) -> dict:
    """Keep exactly the source structure; every value forced to Devanagari + ASCII digits."""
    if not isinstance(translated, dict):
        raise HindiTranslationError('Translation is not a JSON object')
    out = {}
    for key, value in source.items():
        if key == 'medicines':
            continue
        out[key] = ensure_devanagari(str(translated.get(key) or '')) if value else ''
    src_meds = source['medicines']
    tr_meds = translated.get('medicines') or []
    if not isinstance(tr_meds, list) or len(tr_meds) != len(src_meds):
        raise HindiTranslationError('Medicine count mismatch in translation')
    out['medicines'] = []
    for src, tr in zip(src_meds, tr_meds):
        tr = tr if isinstance(tr, dict) else {}
        med = {k: ensure_devanagari(str(tr.get(k) or '')) if v else '' for k, v in src.items()}
        med['frequency'] = local_frequency(src['frequency']) or med['frequency']
        med['duration'] = local_duration(src['duration']) or med['duration']
        out['medicines'].append(med)
    return out


def get_hindi_content(rx) -> dict:
    """Hindi translation of the prescription's clinical content (cached per source hash)."""
    payload = _source_payload(rx)
    digest = _payload_hash(payload)
    cached = rx.hindi_content or {}
    if cached.get('hash') == digest and cached.get('data'):
        return cached['data']

    logger.info('Translating prescription %s to Hindi (de-identified clinical content only)', rx.id)
    try:
        data = _sanitize(payload, _call_claude(payload))
    except HindiTranslationError:
        raise
    except Exception as e:
        logger.exception('Hindi translation failed for rx %s', rx.id)
        raise HindiTranslationError(str(e)) from e

    rx.hindi_content = {'hash': digest, 'data': data}
    rx.save(update_fields=['hindi_content'])
    return data


def build_hindi_print_context(rx) -> dict:
    """Everything the Hindi prescription card prints, as Devanagari strings."""
    visit = rx.visit
    patient = visit.patient
    clinic = visit.clinic
    doctor = rx.doctor
    content = get_hindi_content(rx)

    summary = ensure_devanagari(rx.patient_summary_hi) if rx.patient_summary_hi else content['patient_summary']
    return {
        'clinic_name': clinic_name_hi(clinic),
        'clinic_address': clinic_address_hi(clinic),
        'clinic_phone': to_ascii_digits(clinic.phone),
        'doctor_name': doctor_name_hi(doctor) if doctor else '',
        'doctor_qualification': doctor_qualification_hi(doctor) if doctor else '',
        'doctor_registration': (
            transliterate(doctor.registration_number)
            if doctor and doctor.show_registration_on_rx and doctor.registration_number else ''
        ),
        'patient_name': patient_name_hi(patient),
        'patient_age': f'{patient.age} वर्ष' if patient.age else '',
        'patient_gender': HI_GENDER.get(patient.gender, ''),
        'patient_blood_group': blood_group_hi(patient.blood_group),
        'date': hindi_date(rx.created_at.date()),
        'follow_up_date': hindi_date(rx.follow_up_date),
        'vitals': vitals_hi(visit),
        'summary': summary,
        **{k: v for k, v in content.items() if k != 'patient_summary'},
    }


def hindi_whatsapp_message(rx, share_url: str) -> str:
    patient = rx.visit.patient
    clinic = clinic_name_hi(rx.visit.clinic)
    lines = [
        f'नमस्ते {patient_name_hi(patient)} जी,',
        '',
        f'*{clinic}* से आपका पर्चा तैयार है।',
        '',
        'अपना पर्चा यहाँ देखें और डाउनलोड करें:',
        share_url,
    ]
    if rx.follow_up_date:
        doctor = doctor_name_hi(rx.doctor) if rx.doctor else 'डॉक्टर'
        lines += [
            '',
            f'{clinic} में {doctor} के साथ आपकी अगली मुलाकात *{hindi_date(rx.follow_up_date)}* को है।',
            'कृपया अगली बार यह पर्चा साथ लाएँ।',
        ]
    lines += ['', f'— {clinic}']
    return '\n'.join(lines)
