"""
Seed ~200 clinically important drug-drug interactions for Indian GP practice.
Safe to run multiple times (get_or_create).
"""
from django.core.management.base import BaseCommand
from prescription.models import DrugInteraction

INTERACTIONS = [
    # ── ANTICOAGULANTS ────────────────────────────────────────────────────────
    ("warfarin",       "aspirin",         "major",    "Increased bleeding risk — additive anticoagulant effect", "Pharmacodynamic synergy"),
    ("warfarin",       "ibuprofen",       "major",    "Increased bleeding risk + GI bleed risk", "NSAID inhibits platelet + displaces warfarin from protein binding"),
    ("warfarin",       "diclofenac",      "major",    "Increased bleeding risk + GI bleed", "NSAID + anticoagulant synergy"),
    ("warfarin",       "naproxen",        "major",    "Increased bleeding and GI bleed risk", "NSAID + anticoagulant"),
    ("warfarin",       "azithromycin",    "major",    "Elevated INR / bleeding risk", "CYP2C9 inhibition raises warfarin levels"),
    ("warfarin",       "ciprofloxacin",   "major",    "Elevated INR / bleeding risk", "CYP1A2/CYP2C9 inhibition"),
    ("warfarin",       "fluconazole",     "major",    "Severely elevated INR / bleeding risk", "Strong CYP2C9 inhibitor"),
    ("warfarin",       "metronidazole",   "major",    "Elevated INR / bleeding risk", "CYP2C9 inhibition"),
    ("warfarin",       "amiodarone",      "major",    "Markedly elevated INR / life-threatening bleed", "CYP2C9/CYP3A4 inhibition"),
    ("warfarin",       "rifampicin",      "major",    "Reduced anticoagulant effect — INR may drop dangerously", "Strong CYP inducer reduces warfarin levels"),
    ("warfarin",       "paracetamol",     "moderate", "Mild INR elevation with regular high-dose paracetamol", "Unknown mechanism"),
    ("warfarin",       "carbamazepine",   "major",    "Reduced anticoagulant effect", "CYP2C9 induction"),
    ("warfarin",       "phenytoin",       "major",    "Unpredictable INR changes", "Bidirectional CYP2C9 interaction"),

    # ── ACE INHIBITORS + ARBs ────────────────────────────────────────────────
    ("enalapril",      "spironolactone",  "major",    "Hyperkalaemia risk — potentially fatal", "Additive potassium retention"),
    ("ramipril",       "spironolactone",  "major",    "Hyperkalaemia risk", "Additive K+ retention"),
    ("lisinopril",     "spironolactone",  "major",    "Hyperkalaemia risk", "Additive K+ retention"),
    ("enalapril",      "potassium",       "major",    "Hyperkalaemia", "ACE inhibitor reduces aldosterone → K+ retention"),
    ("ramipril",       "potassium",       "major",    "Hyperkalaemia", "ACE inhibitor + K+ supplement"),
    ("lisinopril",     "potassium",       "major",    "Hyperkalaemia", "ACE inhibitor + K+ supplement"),
    ("telmisartan",    "spironolactone",  "major",    "Hyperkalaemia risk", "ARB + K+-sparing diuretic"),
    ("losartan",       "spironolactone",  "major",    "Hyperkalaemia risk", "ARB + K+-sparing diuretic"),
    ("enalapril",      "nsaid",           "moderate", "Reduced antihypertensive effect + renal impairment risk", "NSAID reduces renal prostaglandins"),
    ("ramipril",       "ibuprofen",       "moderate", "Reduced BP control + acute kidney injury risk", "NSAID reduces renal prostaglandins"),

    # ── METFORMIN ─────────────────────────────────────────────────────────────
    ("metformin",      "alcohol",         "major",    "Lactic acidosis risk — potentially fatal", "Ethanol potentiates metformin-induced lactic acid accumulation"),
    ("metformin",      "contrast",        "major",    "Lactic acidosis risk after iodinated contrast", "Contrast-induced nephropathy + metformin"),
    ("metformin",      "cimetidine",      "moderate", "Increased metformin levels — hypoglycaemia risk", "Cimetidine reduces renal tubular secretion of metformin"),

    # ── FLUOROQUINOLONES ──────────────────────────────────────────────────────
    ("ciprofloxacin",  "theophylline",    "major",    "Theophylline toxicity — seizures, arrhythmia", "CYP1A2 inhibition raises theophylline levels"),
    ("ciprofloxacin",  "tizanidine",      "major",    "Severe hypotension + sedation", "CYP1A2 inhibition raises tizanidine 10-fold"),
    ("ciprofloxacin",  "antacid",         "moderate", "Reduced ciprofloxacin absorption", "Chelation with Mg²⁺/Al³⁺"),
    ("ciprofloxacin",  "warfarin",        "major",    "Elevated INR / bleeding risk", "CYP1A2/CYP2C9 inhibition"),
    ("levofloxacin",   "antacid",         "moderate", "Reduced levofloxacin absorption — chelation", "Give 2 h apart"),
    ("levofloxacin",   "amiodarone",      "major",    "QT prolongation — risk of torsades de pointes", "Additive QT effect"),
    ("ciprofloxacin",  "amiodarone",      "major",    "QT prolongation risk", "Additive QT prolongation"),
    ("moxifloxacin",   "amiodarone",      "major",    "QT prolongation — high risk torsades", "Both prolong QT"),
    ("moxifloxacin",   "ondansetron",     "major",    "QT prolongation", "Additive QT effect"),

    # ── SSRIs / SNRIs ─────────────────────────────────────────────────────────
    ("sertraline",     "tramadol",        "major",    "Serotonin syndrome — fever, agitation, myoclonus", "Additive serotonergic effect"),
    ("fluoxetine",     "tramadol",        "major",    "Serotonin syndrome + seizure risk", "SSRI + opioid serotonin synergy"),
    ("escitalopram",   "tramadol",        "major",    "Serotonin syndrome risk", "Additive serotonin"),
    ("sertraline",     "linezolid",       "major",    "Serotonin syndrome — potentially fatal", "Linezolid is MAOI; additive serotonin"),
    ("fluoxetine",     "linezolid",       "major",    "Serotonin syndrome", "MAOI + SSRI"),
    ("paroxetine",     "tramadol",        "major",    "Serotonin syndrome + reduced tramadol effect", "CYP2D6 inhibition + serotonin"),
    ("sertraline",     "warfarin",        "moderate", "Elevated INR / bleeding risk", "SSRI inhibits platelet aggregation"),
    ("fluoxetine",     "warfarin",        "moderate", "Elevated INR / bleeding risk", "CYP2C9 inhibition + antiplatelet"),
    ("fluoxetine",     "amitriptyline",   "major",    "Amitriptyline toxicity — arrhythmia, seizure", "CYP2D6 inhibition triples amitriptyline levels"),
    ("paroxetine",     "amitriptyline",   "major",    "Tricyclic toxicity", "CYP2D6 inhibition"),

    # ── METHOTREXATE ──────────────────────────────────────────────────────────
    ("methotrexate",   "ibuprofen",       "major",    "Methotrexate toxicity — bone marrow suppression, mucositis", "NSAIDs reduce renal MTX excretion"),
    ("methotrexate",   "diclofenac",      "major",    "Methotrexate toxicity", "NSAID reduces renal MTX excretion"),
    ("methotrexate",   "naproxen",        "major",    "Methotrexate toxicity", "NSAID reduces renal MTX excretion"),
    ("methotrexate",   "aspirin",         "major",    "Methotrexate toxicity", "Salicylate reduces MTX clearance"),
    ("methotrexate",   "cotrimoxazole",   "major",    "Severe bone marrow suppression", "Additive antifolate effect"),
    ("methotrexate",   "trimethoprim",    "major",    "Bone marrow suppression", "Additive antifolate"),
    ("methotrexate",   "penicillin",      "moderate", "Elevated methotrexate levels", "Penicillins compete with MTX for renal secretion"),

    # ── STATINS ───────────────────────────────────────────────────────────────
    ("simvastatin",    "clarithromycin",  "major",    "Rhabdomyolysis — severe muscle breakdown + renal failure", "CYP3A4 inhibition raises simvastatin 10-fold"),
    ("simvastatin",    "erythromycin",    "major",    "Rhabdomyolysis risk", "CYP3A4 inhibition"),
    ("simvastatin",    "fluconazole",     "major",    "Rhabdomyolysis risk", "CYP3A4 inhibition"),
    ("simvastatin",    "amiodarone",      "major",    "Rhabdomyolysis risk — keep dose ≤20 mg", "CYP3A4 inhibition"),
    ("atorvastatin",   "clarithromycin",  "moderate", "Increased statin levels — myopathy risk", "CYP3A4 inhibition (less than simvastatin)"),
    ("atorvastatin",   "erythromycin",    "moderate", "Myopathy risk", "CYP3A4 inhibition"),
    ("rosuvastatin",   "gemfibrozil",     "major",    "Increased rosuvastatin exposure — myopathy", "Inhibits hepatic uptake transporters"),
    ("simvastatin",    "gemfibrozil",     "major",    "Myopathy / rhabdomyolysis", "Inhibits statin metabolism"),

    # ── DIGOXIN ───────────────────────────────────────────────────────────────
    ("digoxin",        "amiodarone",      "major",    "Digoxin toxicity — bradycardia, heart block, arrhythmia", "Amiodarone inhibits P-gp and CYP → doubles digoxin levels"),
    ("digoxin",        "clarithromycin",  "major",    "Digoxin toxicity", "P-gp inhibition raises digoxin"),
    ("digoxin",        "erythromycin",    "major",    "Digoxin toxicity", "P-gp inhibition + gut flora alteration"),
    ("digoxin",        "spironolactone",  "moderate", "Elevated digoxin levels", "Spironolactone reduces renal digoxin clearance"),
    ("digoxin",        "calcium",         "major",    "Life-threatening arrhythmia if IV calcium given rapidly", "Hypercalcaemia potentiates digoxin toxicity"),
    ("digoxin",        "verapamil",       "major",    "Digoxin toxicity — severe bradycardia", "P-gp inhibition + additive AV node depression"),
    ("digoxin",        "diltiazem",       "moderate", "Elevated digoxin levels + AV block", "P-gp inhibition"),

    # ── BETA BLOCKERS ─────────────────────────────────────────────────────────
    ("propranolol",    "verapamil",       "major",    "Severe bradycardia, heart block, cardiac arrest", "Additive negative chronotropy + dromotropy"),
    ("atenolol",       "verapamil",       "major",    "Heart block / cardiac arrest", "Additive AV nodal depression"),
    ("metoprolol",     "verapamil",       "major",    "Severe bradycardia / heart block", "Additive AV nodal block"),
    ("propranolol",    "diltiazem",       "major",    "Bradycardia / heart block", "Additive AV nodal depression"),
    ("propranolol",    "salbutamol",      "major",    "Blocked bronchodilation — severe bronchospasm in asthma", "Beta-blocker antagonises beta-2 bronchodilation"),
    ("atenolol",       "salbutamol",      "major",    "Blocked bronchodilation in asthma/COPD", "Beta-1 blockade + high-dose beta-2 agonist"),
    ("propranolol",    "insulin",         "moderate", "Masked hypoglycaemia symptoms + prolonged hypoglycaemia", "Beta-blockade blunts tachycardia warning"),
    ("atenolol",       "insulin",         "moderate", "Masked hypoglycaemia signs", "Beta-blockade blunts adrenergic response"),

    # ── QT-PROLONGING DRUGS ───────────────────────────────────────────────────
    ("amiodarone",     "azithromycin",    "major",    "QT prolongation — torsades de pointes risk", "Additive QT prolongation"),
    ("amiodarone",     "ondansetron",     "major",    "QT prolongation risk", "Additive QT prolongation"),
    ("haloperidol",    "azithromycin",    "major",    "QT prolongation risk", "Additive QT prolongation"),
    ("haloperidol",    "ondansetron",     "major",    "QT prolongation", "Additive QT effect"),
    ("chlorpromazine", "azithromycin",    "major",    "QT prolongation / torsades", "Additive QT prolongation"),
    ("chlorpromazine", "ondansetron",     "major",    "QT prolongation", "Additive QT"),
    ("domperidone",    "azithromycin",    "major",    "QT prolongation — torsades risk", "Additive QT prolongation"),
    ("domperidone",    "fluconazole",     "major",    "QT prolongation + raised domperidone levels", "CYP3A4 inhibition + QT synergy"),
    ("domperidone",    "erythromycin",    "major",    "QT prolongation + raised domperidone", "CYP3A4 inhibition + QT synergy"),
    ("domperidone",    "clarithromycin",  "major",    "QT prolongation + raised domperidone", "CYP3A4 inhibition + QT"),
    ("ondansetron",    "azithromycin",    "major",    "QT prolongation", "Additive QT effect"),

    # ── RIFAMPICIN (INDUCER) ──────────────────────────────────────────────────
    ("rifampicin",     "warfarin",        "major",    "Greatly reduced anticoagulant effect — INR drops", "Strong CYP2C9/3A4 inducer"),
    ("rifampicin",     "oral contraceptive", "major", "Contraceptive failure", "CYP3A4 induction accelerates hormone metabolism"),
    ("rifampicin",     "verapamil",       "major",    "Near-complete loss of verapamil effect", "CYP3A4 induction"),
    ("rifampicin",     "methadone",       "major",    "Severe withdrawal — loss of analgesia", "CYP3A4/CYP2B6 induction"),
    ("rifampicin",     "phenytoin",       "moderate", "Reduced phenytoin levels — seizure risk", "CYP2C9 induction"),
    ("rifampicin",     "ketoconazole",    "major",    "Greatly reduced antifungal effect", "CYP3A4 induction"),
    ("rifampicin",     "fluconazole",     "major",    "Reduced fluconazole efficacy", "CYP2C9/3A4 induction"),

    # ── ANTIEPILEPTICS ────────────────────────────────────────────────────────
    ("carbamazepine",  "oral contraceptive", "major", "Contraceptive failure", "CYP3A4 induction"),
    ("phenytoin",      "oral contraceptive", "major", "Contraceptive failure", "CYP3A4 induction"),
    ("carbamazepine",  "lithium",         "major",    "Neurotoxicity despite normal lithium levels", "Pharmacodynamic synergy on CNS"),
    ("carbamazepine",  "erythromycin",    "major",    "Carbamazepine toxicity — diplopia, ataxia, vomiting", "CYP3A4 inhibition raises carbamazepine"),
    ("carbamazepine",  "clarithromycin",  "major",    "Carbamazepine toxicity", "CYP3A4 inhibition"),
    ("carbamazepine",  "fluoxetine",      "moderate", "Elevated carbamazepine levels", "CYP3A4 inhibition"),
    ("valproate",      "aspirin",         "major",    "Valproate toxicity — sedation, hepatotoxicity", "Aspirin displaces valproate from protein binding"),
    ("valproate",      "carbamazepine",   "moderate", "Reduced valproate levels + possible toxicity", "Enzyme induction + pharmacodynamic interaction"),
    ("phenytoin",      "fluconazole",     "major",    "Phenytoin toxicity — nystagmus, ataxia, sedation", "CYP2C9 inhibition raises phenytoin"),
    ("phenytoin",      "isoniazid",       "major",    "Phenytoin toxicity", "CYP2C9 inhibition"),

    # ── LITHIUM ───────────────────────────────────────────────────────────────
    ("lithium",        "ibuprofen",       "major",    "Lithium toxicity — tremor, confusion, arrhythmia", "NSAID reduces renal lithium excretion"),
    ("lithium",        "diclofenac",      "major",    "Lithium toxicity", "NSAID reduces renal lithium clearance"),
    ("lithium",        "naproxen",        "major",    "Lithium toxicity", "NSAID reduces renal clearance"),
    ("lithium",        "thiazide",        "major",    "Lithium toxicity — sodium depletion increases Li+ reabsorption", "Thiazide depletes Na+ → Li+ retention"),
    ("lithium",        "furosemide",      "major",    "Lithium toxicity", "Loop diuretic depletes sodium → Li+ retention"),
    ("lithium",        "enalapril",       "moderate", "Elevated lithium levels — toxicity risk", "ACE inhibitor reduces renal Li+ clearance"),
    ("lithium",        "ramipril",        "moderate", "Lithium toxicity risk", "ACE inhibitor reduces renal Li+ clearance"),
    ("lithium",        "haloperidol",     "moderate", "Neurotoxicity + QT prolongation", "Pharmacodynamic synergy"),

    # ── ANTIFUNGALS (AZOLES) ──────────────────────────────────────────────────
    ("fluconazole",    "simvastatin",     "major",    "Rhabdomyolysis risk", "CYP3A4 inhibition raises statin levels"),
    ("fluconazole",    "warfarin",        "major",    "Severely elevated INR / bleeding risk", "CYP2C9 inhibition"),
    ("fluconazole",    "phenytoin",       "major",    "Phenytoin toxicity", "CYP2C9 inhibition"),
    ("fluconazole",    "sulfonylurea",    "major",    "Severe hypoglycaemia", "CYP2C9 inhibition raises glipizide/glibenclamide"),
    ("fluconazole",    "glibenclamide",   "major",    "Severe hypoglycaemia", "CYP2C9 inhibition"),
    ("fluconazole",    "glipizide",       "major",    "Severe hypoglycaemia", "CYP2C9 inhibition"),
    ("ketoconazole",   "simvastatin",     "major",    "Rhabdomyolysis risk", "CYP3A4 inhibition"),
    ("ketoconazole",   "terfenadine",     "major",    "Fatal arrhythmia / QT prolongation", "CYP3A4 inhibition + QT"),

    # ── MACROLIDE ANTIBIOTICS ────────────────────────────────────────────────
    ("erythromycin",   "simvastatin",     "major",    "Rhabdomyolysis risk", "CYP3A4 inhibition"),
    ("erythromycin",   "carbamazepine",   "major",    "Carbamazepine toxicity", "CYP3A4 inhibition"),
    ("erythromycin",   "theophylline",    "major",    "Theophylline toxicity — seizures, arrhythmia", "CYP1A2 inhibition"),
    ("clarithromycin", "simvastatin",     "major",    "Rhabdomyolysis", "CYP3A4 inhibition"),
    ("clarithromycin", "carbamazepine",   "major",    "Carbamazepine toxicity", "CYP3A4 inhibition"),
    ("clarithromycin", "theophylline",    "major",    "Theophylline toxicity", "CYP3A4 inhibition"),
    ("clarithromycin", "warfarin",        "major",    "Elevated INR / bleeding", "CYP2C9 inhibition"),

    # ── THEOPHYLLINE ──────────────────────────────────────────────────────────
    ("theophylline",   "ciprofloxacin",   "major",    "Theophylline toxicity", "CYP1A2 inhibition"),
    ("theophylline",   "erythromycin",    "major",    "Theophylline toxicity", "CYP1A2 inhibition"),
    ("theophylline",   "clarithromycin",  "major",    "Theophylline toxicity", "CYP1A2 inhibition"),
    ("theophylline",   "cimetidine",      "major",    "Theophylline toxicity", "CYP1A2 inhibition"),
    ("theophylline",   "allopurinol",     "moderate", "Elevated theophylline levels", "Xanthine oxidase inhibition reduces theophylline metabolism"),

    # ── OPIOIDS ───────────────────────────────────────────────────────────────
    ("tramadol",       "sertraline",      "major",    "Serotonin syndrome", "Serotonergic synergy"),
    ("tramadol",       "fluoxetine",      "major",    "Serotonin syndrome + reduced analgesia", "CYP2D6 inhibition + serotonin"),
    ("tramadol",       "alcohol",         "major",    "Severe CNS and respiratory depression", "Additive CNS depression"),
    ("morphine",       "alcohol",         "major",    "Respiratory depression — potentially fatal", "Additive CNS/respiratory depression"),
    ("codeine",        "alcohol",         "moderate", "Enhanced CNS depression", "Additive effect"),
    ("fentanyl",       "clarithromycin",  "major",    "Fentanyl toxicity — respiratory depression", "CYP3A4 inhibition raises fentanyl"),

    # ── ANTIDIABETICS ─────────────────────────────────────────────────────────
    ("glibenclamide",  "fluconazole",     "major",    "Severe hypoglycaemia", "CYP2C9 inhibition raises sulfonylurea"),
    ("glipizide",      "fluconazole",     "major",    "Severe hypoglycaemia", "CYP2C9 inhibition"),
    ("insulin",        "alcohol",         "major",    "Severe prolonged hypoglycaemia", "Alcohol inhibits hepatic gluconeogenesis"),
    ("glibenclamide",  "ciprofloxacin",   "moderate", "Hypoglycaemia risk", "Mechanism unclear; documented clinically"),
    ("metformin",      "furosemide",      "moderate", "Increased metformin levels — lactic acidosis risk", "Furosemide reduces renal metformin clearance"),

    # ── CORTICOSTEROIDS ───────────────────────────────────────────────────────
    ("prednisolone",   "ibuprofen",       "major",    "Greatly increased GI ulcer/bleed risk", "Additive mucosal damage"),
    ("dexamethasone",  "ibuprofen",       "major",    "High GI bleed risk", "Additive GI toxicity"),
    ("prednisolone",   "diclofenac",      "major",    "High GI bleed risk", "Additive GI toxicity"),
    ("prednisolone",   "insulin",         "moderate", "Hyperglycaemia — steroid-induced diabetes", "Steroid causes insulin resistance"),
    ("dexamethasone",  "insulin",         "moderate", "Hyperglycaemia requiring insulin dose adjustment", "Glucocorticoid antagonises insulin"),

    # ── ANTIHYPERTENSIVES ─────────────────────────────────────────────────────
    ("amlodipine",     "simvastatin",     "moderate", "Elevated simvastatin levels — myopathy risk (keep <20mg)", "CYP3A4 mild inhibition"),
    ("verapamil",      "digoxin",         "major",    "Digoxin toxicity", "P-gp inhibition + AV node depression"),
    ("clonidine",      "propranolol",     "major",    "Rebound hypertension if clonidine is withdrawn", "Beta-blockade unmasks alpha-mediated vasoconstriction"),
    ("amlodipine",     "rifampicin",      "major",    "Near-complete loss of antihypertensive effect", "CYP3A4 induction"),

    # ── PROTON PUMP INHIBITORS ────────────────────────────────────────────────
    ("omeprazole",     "clopidogrel",     "major",    "Reduced clopidogrel antiplatelet effect — stent thrombosis risk", "CYP2C19 inhibition reduces active metabolite"),
    ("esomeprazole",   "clopidogrel",     "major",    "Reduced clopidogrel effect", "CYP2C19 inhibition"),
    ("omeprazole",     "methotrexate",    "moderate", "Elevated methotrexate — toxicity", "Reduced renal tubular secretion"),

    # ── HIV ANTIRETROVIRALS ───────────────────────────────────────────────────
    ("ritonavir",      "simvastatin",     "major",    "Rhabdomyolysis — simvastatin contraindicated with ritonavir", "Extreme CYP3A4 inhibition raises statin >3000%"),
    ("ritonavir",      "amiodarone",      "major",    "Life-threatening arrhythmia", "CYP3A4 inhibition raises amiodarone"),

    # ── ALLOPURINOL ───────────────────────────────────────────────────────────
    ("allopurinol",    "azathioprine",    "major",    "Azathioprine toxicity — severe bone marrow suppression", "Xanthine oxidase inhibition dramatically raises azathioprine levels"),
    ("allopurinol",    "mercaptopurine",  "major",    "Mercaptopurine toxicity", "Xanthine oxidase inhibition"),
    ("allopurinol",    "warfarin",        "moderate", "Elevated INR", "CYP2C9 inhibition"),
    ("allopurinol",    "ampicillin",      "minor",    "Increased risk of ampicillin rash", "Pharmacodynamic interaction"),

    # ── CLOPIDOGREL ───────────────────────────────────────────────────────────
    ("clopidogrel",    "aspirin",         "moderate", "Increased bleeding risk — additive antiplatelet", "Pharmacodynamic synergy (intentional in many cases — flag for awareness)"),
    ("clopidogrel",    "omeprazole",      "major",    "Reduced antiplatelet effect — stent thrombosis risk", "CYP2C19 inhibition"),

    # ── BISPHOSPHONATES ───────────────────────────────────────────────────────
    ("alendronate",    "antacid",         "major",    "Greatly reduced bisphosphonate absorption", "Chelation — take on empty stomach"),
    ("alendronate",    "calcium",         "major",    "Reduced bisphosphonate absorption", "Chelation"),

    # ── TETRACYCLINES ─────────────────────────────────────────────────────────
    ("doxycycline",    "antacid",         "major",    "Greatly reduced doxycycline absorption", "Chelation with Mg²⁺/Ca²⁺/Al³⁺"),
    ("doxycycline",    "calcium",         "major",    "Reduced absorption", "Chelation"),
    ("doxycycline",    "iron",            "major",    "Reduced doxycycline absorption", "Chelation"),
    ("tetracycline",   "antacid",         "major",    "Reduced absorption", "Chelation"),
    ("tetracycline",   "iron",            "major",    "Reduced absorption — chelation", "Chelation"),

    # ── MISCELLANEOUS ─────────────────────────────────────────────────────────
    ("sildenafil",     "nitrate",         "major",    "Severe hypotension — potentially fatal", "Additive vasodilation (nitric oxide pathway synergy)"),
    ("tadalafil",      "nitrate",         "major",    "Severe / fatal hypotension", "Additive vasodilation"),
    ("sildenafil",     "nitroglycerin",   "major",    "Severe hypotension", "Additive NO-mediated vasodilation"),
    ("tramadol",       "carbamazepine",   "moderate", "Reduced tramadol effect + seizure risk", "CYP3A4 induction reduces tramadol; lowers seizure threshold"),
    ("isoniazid",      "phenytoin",       "major",    "Phenytoin toxicity", "CYP2C9 inhibition"),
    ("isoniazid",      "carbamazepine",   "moderate", "Carbamazepine toxicity", "CYP3A4 inhibition"),
    ("isoniazid",      "alcohol",         "major",    "Hepatotoxicity risk — potentially severe", "Additive hepatotoxicity"),
    ("ketoconazole",   "alcohol",         "major",    "Hepatotoxicity risk + antabuse-like reaction", "Disulfiram-like reaction + hepatotoxicity"),
    ("metronidazole",  "alcohol",         "major",    "Disulfiram-like reaction — severe nausea, flushing, palpitations", "Acetaldehyde accumulation"),
    ("tinidazole",     "alcohol",         "major",    "Disulfiram-like reaction", "Same mechanism as metronidazole-alcohol"),
]


class Command(BaseCommand):
    help = "Seed drug-drug interaction pairs (safe to run multiple times)"

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-seed even if data exists')

    def handle(self, *args, **options):
        if not options.get('force') and DrugInteraction.objects.count() >= 100:
            self.stdout.write('Drug interactions already seeded. Skipping. Use --force to re-seed.')
            return
        created = 0
        updated = 0
        for d1, d2, sev, effect, mech in INTERACTIONS:
            # Normalise — always store alphabetically to avoid duplicates
            if d1 > d2:
                d1, d2 = d2, d1
            obj, is_new = DrugInteraction.objects.update_or_create(
                drug1_keyword=d1,
                drug2_keyword=d2,
                defaults={'severity': sev, 'effect': effect, 'mechanism': mech},
            )
            if is_new:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f"Drug interactions: {created} created, {updated} updated. Total: {DrugInteraction.objects.count()}"
        ))
