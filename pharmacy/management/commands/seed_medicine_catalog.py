"""Seed ~500 top Indian medicines into MedicineCatalog."""
from django.core.management.base import BaseCommand
from pharmacy.models import MedicineCatalog


class Command(BaseCommand):
    help = 'Seed medicine catalog with ~500 top Indian medicines'

    def handle(self, *args, **options):
        if MedicineCatalog.objects.exists():
            self.stdout.write('MedicineCatalog already seeded — skipping. Use shell to reseed.')
            return
        items = []

        def m(name, generic, form='Tab', manufacturer='', category=''):
            return MedicineCatalog(name=name, generic_name=generic, form=form, manufacturer=manufacturer, category=category)

        # ── Anti-diabetics ─────────────────────────────────────────────
        cat = 'Anti-diabetic'
        items += [
            m('Metformin 500mg', 'Metformin Hydrochloride', 'Tab', 'USV', cat),
            m('Metformin 850mg', 'Metformin Hydrochloride', 'Tab', 'USV', cat),
            m('Metformin 1000mg', 'Metformin Hydrochloride', 'Tab', 'USV', cat),
            m('Glycomet 500mg', 'Metformin Hydrochloride', 'Tab', 'USV', cat),
            m('Glycomet 850mg', 'Metformin Hydrochloride', 'Tab', 'USV', cat),
            m('Glucophage 500mg', 'Metformin Hydrochloride', 'Tab', 'Merck', cat),
            m('Glimepiride 1mg', 'Glimepiride', 'Tab', 'Sanofi', cat),
            m('Glimepiride 2mg', 'Glimepiride', 'Tab', 'Sanofi', cat),
            m('Amaryl 1mg', 'Glimepiride', 'Tab', 'Sanofi', cat),
            m('Amaryl 2mg', 'Glimepiride', 'Tab', 'Sanofi', cat),
            m('Glimisave 1mg', 'Glimepiride', 'Tab', 'Eris', cat),
            m('Glimisave 2mg', 'Glimepiride', 'Tab', 'Eris', cat),
            m('Glipizide 5mg', 'Glipizide', 'Tab', 'Pfizer', cat),
            m('Sitagliptin 100mg', 'Sitagliptin', 'Tab', 'MSD', cat),
            m('Januvia 100mg', 'Sitagliptin', 'Tab', 'MSD', cat),
            m('Vildagliptin 50mg', 'Vildagliptin', 'Tab', 'Novartis', cat),
            m('Galvus 50mg', 'Vildagliptin', 'Tab', 'Novartis', cat),
            m('Dapagliflozin 10mg', 'Dapagliflozin', 'Tab', 'AstraZeneca', cat),
            m('Forxiga 10mg', 'Dapagliflozin', 'Tab', 'AstraZeneca', cat),
            m('Empagliflozin 10mg', 'Empagliflozin', 'Tab', 'Boehringer Ingelheim', cat),
            m('Jardiance 10mg', 'Empagliflozin', 'Tab', 'Boehringer Ingelheim', cat),
            m('Insulin Regular (Actrapid)', 'Human Insulin Regular', 'Inj', 'Novo Nordisk', cat),
            m('Insulin Glargine (Lantus)', 'Insulin Glargine', 'Inj', 'Sanofi', cat),
            m('Metformin SR 500mg', 'Metformin Hydrochloride SR', 'Tab', 'USV', cat),
            m('Glimepiride+Metformin 1mg/500mg', 'Glimepiride+Metformin', 'Tab', 'Sanofi', cat),
            m('Glimepiride+Metformin 2mg/500mg', 'Glimepiride+Metformin', 'Tab', 'Sanofi', cat),
        ]

        # ── Anti-hypertensives ─────────────────────────────────────────
        cat = 'Anti-hypertensive'
        items += [
            m('Amlodipine 5mg', 'Amlodipine Besylate', 'Tab', 'Pfizer', cat),
            m('Amlodipine 10mg', 'Amlodipine Besylate', 'Tab', 'Pfizer', cat),
            m('Stamlo 5mg', 'Amlodipine Besylate', 'Tab', 'Dr. Reddy', cat),
            m('Amlokind 5mg', 'Amlodipine Besylate', 'Tab', 'Mankind', cat),
            m('Losartan 50mg', 'Losartan Potassium', 'Tab', 'MSD', cat),
            m('Losartan 100mg', 'Losartan Potassium', 'Tab', 'MSD', cat),
            m('Losar 50mg', 'Losartan Potassium', 'Tab', 'Cipla', cat),
            m('Covance 50mg', 'Losartan Potassium', 'Tab', 'Cipla', cat),
            m('Telmisartan 40mg', 'Telmisartan', 'Tab', 'Boehringer Ingelheim', cat),
            m('Telmisartan 80mg', 'Telmisartan', 'Tab', 'Boehringer Ingelheim', cat),
            m('Telsartan 40mg', 'Telmisartan', 'Tab', 'Glenmark', cat),
            m('Ramipril 2.5mg', 'Ramipril', 'Cap', 'Sanofi', cat),
            m('Ramipril 5mg', 'Ramipril', 'Cap', 'Sanofi', cat),
            m('Ramipril 10mg', 'Ramipril', 'Cap', 'Sanofi', cat),
            m('Cardace 2.5mg', 'Ramipril', 'Cap', 'Sanofi', cat),
            m('Cardace 5mg', 'Ramipril', 'Cap', 'Sanofi', cat),
            m('Atenolol 25mg', 'Atenolol', 'Tab', 'AstraZeneca', cat),
            m('Atenolol 50mg', 'Atenolol', 'Tab', 'AstraZeneca', cat),
            m('Tenormin 50mg', 'Atenolol', 'Tab', 'AstraZeneca', cat),
            m('Aten 25mg', 'Atenolol', 'Tab', 'Zydus', cat),
            m('Metoprolol 25mg', 'Metoprolol Succinate', 'Tab', 'AstraZeneca', cat),
            m('Metoprolol 50mg', 'Metoprolol Succinate', 'Tab', 'AstraZeneca', cat),
            m('Metolar 25mg', 'Metoprolol Succinate', 'Tab', 'Cipla', cat),
            m('Nebivolol 5mg', 'Nebivolol', 'Tab', 'Menarini', cat),
            m('Nebicard 5mg', 'Nebivolol', 'Tab', 'Torrent', cat),
            m('Hydrochlorothiazide 12.5mg', 'Hydrochlorothiazide', 'Tab', 'Cipla', cat),
            m('Hydrochlorothiazide 25mg', 'Hydrochlorothiazide', 'Tab', 'Cipla', cat),
            m('Furosemide 20mg', 'Furosemide', 'Tab', 'Sanofi', cat),
            m('Furosemide 40mg', 'Furosemide', 'Tab', 'Sanofi', cat),
            m('Lasix 40mg', 'Furosemide', 'Tab', 'Sanofi', cat),
            m('Spironolactone 25mg', 'Spironolactone', 'Tab', 'Pfizer', cat),
            m('Spironolactone 50mg', 'Spironolactone', 'Tab', 'Pfizer', cat),
            m('Aldactone 25mg', 'Spironolactone', 'Tab', 'Pfizer', cat),
            m('Nifedipine 10mg', 'Nifedipine', 'Tab', 'Bayer', cat),
            m('Nifedipine 20mg', 'Nifedipine', 'Tab', 'Bayer', cat),
            m('Adalat 10mg', 'Nifedipine', 'Tab', 'Bayer', cat),
            m('Telmisartan+Amlodipine 40/5mg', 'Telmisartan+Amlodipine', 'Tab', 'Boehringer Ingelheim', cat),
        ]

        # ── Antibiotics ────────────────────────────────────────────────
        cat = 'Antibiotic'
        items += [
            m('Amoxicillin 500mg', 'Amoxicillin', 'Cap', 'Cipla', cat),
            m('Mox 500mg', 'Amoxicillin', 'Cap', 'Ranbaxy', cat),
            m('Amoxicillin+Clavulanate 625mg', 'Amoxicillin+Clavulanate', 'Tab', 'GlaxoSmithKline', cat),
            m('Amoxicillin+Clavulanate 1000mg', 'Amoxicillin+Clavulanate', 'Tab', 'GlaxoSmithKline', cat),
            m('Augmentin 625mg', 'Amoxicillin+Clavulanate', 'Tab', 'GlaxoSmithKline', cat),
            m('Amoxyclav 625mg', 'Amoxicillin+Clavulanate', 'Tab', 'Cipla', cat),
            m('Azithromycin 250mg', 'Azithromycin', 'Tab', 'Cipla', cat),
            m('Azithromycin 500mg', 'Azithromycin', 'Tab', 'Cipla', cat),
            m('Azithral 500mg', 'Azithromycin', 'Tab', 'Alembic', cat),
            m('Zithromax 500mg', 'Azithromycin', 'Tab', 'Pfizer', cat),
            m('Ciprofloxacin 500mg', 'Ciprofloxacin', 'Tab', 'Cipla', cat),
            m('Ciprofloxacin 1000mg', 'Ciprofloxacin', 'Tab', 'Cipla', cat),
            m('Ciplox 500mg', 'Ciprofloxacin', 'Tab', 'Cipla', cat),
            m('Cifran 500mg', 'Ciprofloxacin', 'Tab', 'Ranbaxy', cat),
            m('Levofloxacin 500mg', 'Levofloxacin', 'Tab', 'Sanofi', cat),
            m('Levofloxacin 750mg', 'Levofloxacin', 'Tab', 'Sanofi', cat),
            m('Levoquin 500mg', 'Levofloxacin', 'Tab', 'Cipla', cat),
            m('Doxycycline 100mg', 'Doxycycline', 'Cap', 'Cipla', cat),
            m('Doxolin 100mg', 'Doxycycline', 'Cap', 'Alembic', cat),
            m('Cefpodoxime 200mg', 'Cefpodoxime Proxetil', 'Tab', 'Sun Pharma', cat),
            m('Cepodem 200mg', 'Cefpodoxime Proxetil', 'Tab', 'Sun Pharma', cat),
            m('Cefixime 200mg', 'Cefixime', 'Tab', 'Alkem', cat),
            m('Cefixime 400mg', 'Cefixime', 'Tab', 'Alkem', cat),
            m('Taxim-O 200mg', 'Cefixime', 'Tab', 'Alkem', cat),
            m('Metronidazole 400mg', 'Metronidazole', 'Tab', 'Abbott', cat),
            m('Metronidazole 500mg', 'Metronidazole', 'Tab', 'Abbott', cat),
            m('Flagyl 400mg', 'Metronidazole', 'Tab', 'Abbott', cat),
            m('Metrogyl 400mg', 'Metronidazole', 'Tab', 'J.B. Chemicals', cat),
            m('Nitrofurantoin 100mg', 'Nitrofurantoin', 'Cap', 'Cipla', cat),
            m('Nitrofur 100mg', 'Nitrofurantoin', 'Cap', 'Cipla', cat),
            m('Cloxacillin 500mg', 'Cloxacillin', 'Cap', 'Cipla', cat),
            m('Clindamycin 150mg', 'Clindamycin', 'Cap', 'Pfizer', cat),
            m('Clindamycin 300mg', 'Clindamycin', 'Cap', 'Pfizer', cat),
            m('Dalacin-C 150mg', 'Clindamycin', 'Cap', 'Pfizer', cat),
            m('Co-trimoxazole 480mg', 'Trimethoprim+Sulfamethoxazole', 'Tab', 'Roche', cat),
            m('Co-trimoxazole 960mg', 'Trimethoprim+Sulfamethoxazole', 'Tab', 'Roche', cat),
            m('Bactrim 480mg', 'Trimethoprim+Sulfamethoxazole', 'Tab', 'Roche', cat),
            m('Septran 480mg', 'Trimethoprim+Sulfamethoxazole', 'Tab', 'GlaxoSmithKline', cat),
        ]

        # ── Analgesics / Antipyretics ───────────────────────────────────
        cat = 'Analgesic/Antipyretic'
        items += [
            m('Paracetamol 500mg', 'Paracetamol', 'Tab', 'GlaxoSmithKline', cat),
            m('Paracetamol 650mg', 'Paracetamol', 'Tab', 'Micro Labs', cat),
            m('Paracetamol 1000mg', 'Paracetamol', 'Tab', 'Micro Labs', cat),
            m('Crocin 500mg', 'Paracetamol', 'Tab', 'GlaxoSmithKline', cat),
            m('Dolo 650mg', 'Paracetamol', 'Tab', 'Micro Labs', cat),
            m('Calpol 500mg', 'Paracetamol', 'Tab', 'GlaxoSmithKline', cat),
            m('Ibuprofen 400mg', 'Ibuprofen', 'Tab', 'Abbott', cat),
            m('Ibuprofen 600mg', 'Ibuprofen', 'Tab', 'Abbott', cat),
            m('Ibuprofen 800mg', 'Ibuprofen', 'Tab', 'Abbott', cat),
            m('Brufen 400mg', 'Ibuprofen', 'Tab', 'Abbott', cat),
            m('Combiflam', 'Ibuprofen+Paracetamol', 'Tab', 'Sanofi', cat),
            m('Diclofenac 50mg', 'Diclofenac Sodium', 'Tab', 'Novartis', cat),
            m('Diclofenac 75mg', 'Diclofenac Sodium', 'Tab', 'Novartis', cat),
            m('Voveran 50mg', 'Diclofenac Sodium', 'Tab', 'Novartis', cat),
            m('Aceclofenac 100mg', 'Aceclofenac', 'Tab', 'Cipla', cat),
            m('Zerodol 100mg', 'Aceclofenac', 'Tab', 'Ipca', cat),
            m('Aceclofenac+Paracetamol', 'Aceclofenac+Paracetamol', 'Tab', 'Ipca', cat),
            m('Zerodol-P', 'Aceclofenac+Paracetamol', 'Tab', 'Ipca', cat),
            m('Nimesulide 100mg', 'Nimesulide', 'Tab', 'Reckitt', cat),
            m('Nimulid 100mg', 'Nimesulide', 'Tab', 'Panacea', cat),
            m('Nicip 100mg', 'Nimesulide', 'Tab', 'Cipla', cat),
            m('Etoricoxib 60mg', 'Etoricoxib', 'Tab', 'MSD', cat),
            m('Etoricoxib 90mg', 'Etoricoxib', 'Tab', 'MSD', cat),
            m('Etoricoxib 120mg', 'Etoricoxib', 'Tab', 'MSD', cat),
            m('Arcoxia 60mg', 'Etoricoxib', 'Tab', 'MSD', cat),
            m('Tramadol 50mg', 'Tramadol Hydrochloride', 'Tab', 'Cipla', cat),
            m('Ultracet', 'Tramadol+Paracetamol', 'Tab', 'Janssen', cat),
            m('Ketorolac 10mg', 'Ketorolac Tromethamine', 'Tab', 'Sun Pharma', cat),
            m('Mefenamic Acid 250mg', 'Mefenamic Acid', 'Cap', 'Cipla', cat),
            m('Mefenamic Acid 500mg', 'Mefenamic Acid', 'Tab', 'Cipla', cat),
            m('Meftal 500mg', 'Mefenamic Acid', 'Tab', 'Blue Cross', cat),
        ]

        # ── PPIs / Antacids ────────────────────────────────────────────
        cat = 'GI / Antacid'
        items += [
            m('Pantoprazole 20mg', 'Pantoprazole', 'Tab', 'Wyeth', cat),
            m('Pantoprazole 40mg', 'Pantoprazole', 'Tab', 'Wyeth', cat),
            m('Pan 40mg', 'Pantoprazole', 'Tab', 'Alkem', cat),
            m('Pantocid 40mg', 'Pantoprazole', 'Tab', 'Sun Pharma', cat),
            m('Omeprazole 20mg', 'Omeprazole', 'Cap', 'AstraZeneca', cat),
            m('Omeprazole 40mg', 'Omeprazole', 'Cap', 'AstraZeneca', cat),
            m('Omez 20mg', 'Omeprazole', 'Cap', 'Dr. Reddy', cat),
            m('Ocid 20mg', 'Omeprazole', 'Cap', 'Cipla', cat),
            m('Rabeprazole 20mg', 'Rabeprazole', 'Tab', 'Eisai', cat),
            m('Razo 20mg', 'Rabeprazole', 'Tab', 'Dr. Reddy', cat),
            m('Rablet 20mg', 'Rabeprazole', 'Tab', 'Lupin', cat),
            m('Esomeprazole 20mg', 'Esomeprazole', 'Tab', 'AstraZeneca', cat),
            m('Esomeprazole 40mg', 'Esomeprazole', 'Tab', 'AstraZeneca', cat),
            m('Nexovas 40mg', 'Esomeprazole', 'Tab', 'Cipla', cat),
            m('Lansoprazole 15mg', 'Lansoprazole', 'Cap', 'TAP', cat),
            m('Lansoprazole 30mg', 'Lansoprazole', 'Cap', 'TAP', cat),
            m('Lanzol 30mg', 'Lansoprazole', 'Cap', 'Piramal', cat),
            m('Domperidone 10mg', 'Domperidone', 'Tab', 'Janssen', cat),
            m('Domstal 10mg', 'Domperidone', 'Tab', 'Torrent', cat),
            m('Ondansetron 4mg', 'Ondansetron', 'Tab', 'GlaxoSmithKline', cat),
            m('Ondansetron 8mg', 'Ondansetron', 'Tab', 'GlaxoSmithKline', cat),
            m('Emeset 4mg', 'Ondansetron', 'Tab', 'Cipla', cat),
            m('Ondem 4mg', 'Ondansetron', 'Tab', 'Alkem', cat),
            m('Metoclopramide 10mg', 'Metoclopramide', 'Tab', 'Sanofi', cat),
            m('Perinorm 10mg', 'Metoclopramide', 'Tab', 'Ipca', cat),
            m('Antacid suspension (Gelusil)', 'Aluminium+Magnesium Hydroxide', 'Syp', 'Pfizer', cat),
            m('Digene Gel', 'Aluminium+Magnesium Hydroxide', 'Syp', 'Abbott', cat),
            m('Ranitidine 150mg', 'Ranitidine', 'Tab', 'GlaxoSmithKline', cat),
            m('Ranitidine 300mg', 'Ranitidine', 'Tab', 'GlaxoSmithKline', cat),
        ]

        # ── Anti-allergics ─────────────────────────────────────────────
        cat = 'Anti-allergic'
        items += [
            m('Cetirizine 10mg', 'Cetirizine Hydrochloride', 'Tab', 'UCB', cat),
            m('Cetiriz 10mg', 'Cetirizine Hydrochloride', 'Tab', 'Cipla', cat),
            m('Zyrtec 10mg', 'Cetirizine Hydrochloride', 'Tab', 'UCB', cat),
            m('Levocetirizine 5mg', 'Levocetirizine', 'Tab', 'UCB', cat),
            m('Levocet 5mg', 'Levocetirizine', 'Tab', 'Cipla', cat),
            m('Xyzal 5mg', 'Levocetirizine', 'Tab', 'UCB', cat),
            m('Fexofenadine 120mg', 'Fexofenadine', 'Tab', 'Sanofi', cat),
            m('Fexofenadine 180mg', 'Fexofenadine', 'Tab', 'Sanofi', cat),
            m('Allegra 120mg', 'Fexofenadine', 'Tab', 'Sanofi', cat),
            m('Loratadine 10mg', 'Loratadine', 'Tab', 'Schering-Plough', cat),
            m('Clarityn 10mg', 'Loratadine', 'Tab', 'Schering-Plough', cat),
            m('Chlorpheniramine 4mg', 'Chlorpheniramine Maleate', 'Tab', 'Glaxo', cat),
            m('Piriton 4mg', 'Chlorpheniramine Maleate', 'Tab', 'Glaxo', cat),
            m('Montelukast 10mg', 'Montelukast', 'Tab', 'MSD', cat),
            m('Singulair 10mg', 'Montelukast', 'Tab', 'MSD', cat),
            m('Montair 10mg', 'Montelukast', 'Tab', 'Cipla', cat),
            m('Montelukast+Levocetirizine', 'Montelukast+Levocetirizine', 'Tab', 'Cipla', cat),
            m('Montair-LC', 'Montelukast+Levocetirizine', 'Tab', 'Cipla', cat),
            m('Prednisolone 5mg', 'Prednisolone', 'Tab', 'Wyeth', cat),
            m('Prednisolone 10mg', 'Prednisolone', 'Tab', 'Wyeth', cat),
            m('Prednisolone 20mg', 'Prednisolone', 'Tab', 'Wyeth', cat),
            m('Prednisolone 40mg', 'Prednisolone', 'Tab', 'Wyeth', cat),
            m('Wysolone 5mg', 'Prednisolone', 'Tab', 'Pfizer', cat),
            m('Dexamethasone 0.5mg', 'Dexamethasone', 'Tab', 'MSD', cat),
            m('Dexamethasone 4mg', 'Dexamethasone', 'Tab', 'MSD', cat),
            m('Dexamethasone 8mg', 'Dexamethasone', 'Tab', 'MSD', cat),
        ]

        # ── Cardiac ────────────────────────────────────────────────────
        cat = 'Cardiac'
        items += [
            m('Aspirin 75mg', 'Aspirin', 'Tab', 'Bayer', cat),
            m('Aspirin 150mg', 'Aspirin', 'Tab', 'Bayer', cat),
            m('Aspirin 325mg', 'Aspirin', 'Tab', 'Bayer', cat),
            m('Ecosprin 75mg', 'Aspirin', 'Tab', 'USV', cat),
            m('Clopidogrel 75mg', 'Clopidogrel', 'Tab', 'Sanofi', cat),
            m('Plavix 75mg', 'Clopidogrel', 'Tab', 'Sanofi', cat),
            m('Clopilet 75mg', 'Clopidogrel', 'Tab', 'Sun Pharma', cat),
            m('Atorvastatin 10mg', 'Atorvastatin', 'Tab', 'Pfizer', cat),
            m('Atorvastatin 20mg', 'Atorvastatin', 'Tab', 'Pfizer', cat),
            m('Atorvastatin 40mg', 'Atorvastatin', 'Tab', 'Pfizer', cat),
            m('Lipitor 10mg', 'Atorvastatin', 'Tab', 'Pfizer', cat),
            m('Atorva 10mg', 'Atorvastatin', 'Tab', 'Zydus', cat),
            m('Rosuvastatin 5mg', 'Rosuvastatin', 'Tab', 'AstraZeneca', cat),
            m('Rosuvastatin 10mg', 'Rosuvastatin', 'Tab', 'AstraZeneca', cat),
            m('Rosuvastatin 20mg', 'Rosuvastatin', 'Tab', 'AstraZeneca', cat),
            m('Crestor 10mg', 'Rosuvastatin', 'Tab', 'AstraZeneca', cat),
            m('Rozucor 10mg', 'Rosuvastatin', 'Tab', 'Sun Pharma', cat),
            m('Digoxin 0.25mg', 'Digoxin', 'Tab', 'GlaxoSmithKline', cat),
            m('Lanoxin 0.25mg', 'Digoxin', 'Tab', 'GlaxoSmithKline', cat),
            m('Isosorbide Mononitrate 10mg', 'Isosorbide Mononitrate', 'Tab', 'Solvay', cat),
            m('Isosorbide Mononitrate 20mg', 'Isosorbide Mononitrate', 'Tab', 'Solvay', cat),
            m('Isosorbide Mononitrate 60mg', 'Isosorbide Mononitrate', 'Tab', 'Solvay', cat),
            m('Isosorb 20mg', 'Isosorbide Mononitrate', 'Tab', 'Nicholas Piramal', cat),
            m('Nitroglycerin 0.5mg', 'Nitroglycerin', 'Tab', 'Nicholas Piramal', cat),
            m('Sorbitrate 5mg', 'Isosorbide Dinitrate', 'Tab', 'AstraZeneca', cat),
            m('Warfarin 1mg', 'Warfarin Sodium', 'Tab', 'Bristol-Myers', cat),
            m('Warfarin 2mg', 'Warfarin Sodium', 'Tab', 'Bristol-Myers', cat),
            m('Warfarin 5mg', 'Warfarin Sodium', 'Tab', 'Bristol-Myers', cat),
            m('Rivaroxaban 10mg', 'Rivaroxaban', 'Tab', 'Bayer', cat),
            m('Rivaroxaban 15mg', 'Rivaroxaban', 'Tab', 'Bayer', cat),
            m('Rivaroxaban 20mg', 'Rivaroxaban', 'Tab', 'Bayer', cat),
            m('Apixaban 2.5mg', 'Apixaban', 'Tab', 'Bristol-Myers', cat),
            m('Apixaban 5mg', 'Apixaban', 'Tab', 'Bristol-Myers', cat),
            m('Amiodarone 100mg', 'Amiodarone', 'Tab', 'Sanofi', cat),
            m('Amiodarone 200mg', 'Amiodarone', 'Tab', 'Sanofi', cat),
            m('Carvedilol 3.125mg', 'Carvedilol', 'Tab', 'Roche', cat),
            m('Carvedilol 6.25mg', 'Carvedilol', 'Tab', 'Roche', cat),
            m('Carvedilol 12.5mg', 'Carvedilol', 'Tab', 'Roche', cat),
            m('Bisoprolol 2.5mg', 'Bisoprolol', 'Tab', 'Merck', cat),
            m('Bisoprolol 5mg', 'Bisoprolol', 'Tab', 'Merck', cat),
            m('Bisoprolol 10mg', 'Bisoprolol', 'Tab', 'Merck', cat),
        ]

        # ── Bronchodilators ────────────────────────────────────────────
        cat = 'Bronchodilator'
        items += [
            m('Salbutamol 2mg', 'Salbutamol', 'Tab', 'GlaxoSmithKline', cat),
            m('Salbutamol 4mg', 'Salbutamol', 'Tab', 'GlaxoSmithKline', cat),
            m('Salbutamol Inhaler 100mcg', 'Salbutamol', 'Inhaler', 'GlaxoSmithKline', cat),
            m('Asthalin Inhaler', 'Salbutamol', 'Inhaler', 'Cipla', cat),
            m('Ventolin Inhaler', 'Salbutamol', 'Inhaler', 'GlaxoSmithKline', cat),
            m('Ipratropium Inhaler (Duolin)', 'Ipratropium+Salbutamol', 'Inhaler', 'Cipla', cat),
            m('Formoterol+Budesonide Inhaler (Foracort)', 'Formoterol+Budesonide', 'Inhaler', 'Cipla', cat),
            m('Symbicort Inhaler', 'Formoterol+Budesonide', 'Inhaler', 'AstraZeneca', cat),
            m('Tiotropium 18mcg (Spiriva)', 'Tiotropium', 'Inhaler', 'Boehringer Ingelheim', cat),
            m('Theophylline 100mg', 'Theophylline', 'Tab', 'Torrent', cat),
            m('Theophylline 200mg', 'Theophylline', 'Tab', 'Torrent', cat),
            m('Theophylline 300mg', 'Theophylline', 'Tab', 'Torrent', cat),
            m('Bambuterol 10mg', 'Bambuterol', 'Tab', 'AstraZeneca', cat),
            m('Salmeterol+Fluticasone Inhaler (Seretide)', 'Salmeterol+Fluticasone', 'Inhaler', 'GlaxoSmithKline', cat),
        ]

        # ── Vitamins / Supplements ─────────────────────────────────────
        cat = 'Vitamin/Supplement'
        items += [
            m('Vitamin B-complex (Becosules)', 'Vitamin B Complex', 'Cap', 'Pfizer', cat),
            m('Neurobion Forte', 'Vitamin B Complex', 'Tab', 'Merck', cat),
            m('Vitamin C 500mg', 'Ascorbic Acid', 'Tab', 'Cipla', cat),
            m('Vitamin C 1000mg', 'Ascorbic Acid', 'Tab', 'Cipla', cat),
            m('Vitamin D3 60000IU', 'Cholecalciferol', 'Cap', 'Cadila', cat),
            m('Calcirol 60000IU', 'Cholecalciferol', 'Cap', 'Cadila', cat),
            m('Uprise-D3 60000IU', 'Cholecalciferol', 'Cap', 'Pfizer', cat),
            m('Calcium+Vitamin D3 (Shelcal)', 'Calcium Carbonate+Cholecalciferol', 'Tab', 'Elder', cat),
            m('Calcimax 500mg', 'Calcium Carbonate+Vitamin D3', 'Tab', 'Meyer', cat),
            m('Ferrous Sulphate 300mg', 'Ferrous Sulphate', 'Tab', 'Cipla', cat),
            m('Iron+Folic Acid (Orofer XT)', 'Iron+Folic Acid', 'Tab', 'Emcure', cat),
            m('Dexorange Syrup', 'Iron+Vitamin B12+Folic Acid', 'Syp', 'Franco-Indian', cat),
            m('Folic Acid 5mg', 'Folic Acid', 'Tab', 'Cipla', cat),
            m('Methylcobalamin 500mcg', 'Methylcobalamin', 'Tab', 'Sun Pharma', cat),
            m('Methylcobalamin 1500mcg', 'Methylcobalamin', 'Tab', 'Sun Pharma', cat),
            m('Mecobal 500mcg', 'Methylcobalamin', 'Tab', 'Elder', cat),
            m('Methycobal 500mcg', 'Methylcobalamin', 'Tab', 'Eisai', cat),
            m('Alpha-Lipoic Acid 100mg', 'Alpha-Lipoic Acid', 'Tab', 'Cipla', cat),
            m('Zinc 50mg', 'Zinc Sulphate', 'Tab', 'Cipla', cat),
            m('Multivitamin (Supradyn)', 'Multivitamin', 'Tab', 'Bayer', cat),
        ]

        # ── NSAIDs ─────────────────────────────────────────────────────
        cat = 'NSAID'
        items += [
            m('Indomethacin 25mg', 'Indomethacin', 'Cap', 'Cipla', cat),
            m('Indomethacin 50mg', 'Indomethacin', 'Cap', 'Cipla', cat),
            m('Indocap 25mg', 'Indomethacin', 'Cap', 'Cipla', cat),
            m('Piroxicam 20mg', 'Piroxicam', 'Tab', 'Pfizer', cat),
            m('Feldene 20mg', 'Piroxicam', 'Tab', 'Pfizer', cat),
            m('Naproxen 250mg', 'Naproxen', 'Tab', 'Roche', cat),
            m('Naproxen 500mg', 'Naproxen', 'Tab', 'Roche', cat),
            m('Naprosyn 500mg', 'Naproxen', 'Tab', 'Roche', cat),
            m('Celecoxib 100mg', 'Celecoxib', 'Cap', 'Pfizer', cat),
            m('Celecoxib 200mg', 'Celecoxib', 'Cap', 'Pfizer', cat),
            m('Celebrex 200mg', 'Celecoxib', 'Cap', 'Pfizer', cat),
            m('Celact 200mg', 'Celecoxib', 'Cap', 'Cipla', cat),
        ]

        # ── Thyroid ────────────────────────────────────────────────────
        cat = 'Thyroid'
        items += [
            m('Thyroxine 25mcg', 'Levothyroxine', 'Tab', 'Merck', cat),
            m('Thyroxine 50mcg', 'Levothyroxine', 'Tab', 'Merck', cat),
            m('Thyroxine 75mcg', 'Levothyroxine', 'Tab', 'Merck', cat),
            m('Thyroxine 100mcg', 'Levothyroxine', 'Tab', 'Merck', cat),
            m('Eltroxin 50mcg', 'Levothyroxine', 'Tab', 'GlaxoSmithKline', cat),
            m('Thyronorm 50mcg', 'Levothyroxine', 'Tab', 'Abbott', cat),
            m('Carbimazole 5mg', 'Carbimazole', 'Tab', 'Nicholas Piramal', cat),
            m('Carbimazole 10mg', 'Carbimazole', 'Tab', 'Nicholas Piramal', cat),
            m('Carbimazole 20mg', 'Carbimazole', 'Tab', 'Nicholas Piramal', cat),
            m('Neo-Mercazole 5mg', 'Carbimazole', 'Tab', 'Nicholas Piramal', cat),
            m('Propylthiouracil 50mg', 'Propylthiouracil', 'Tab', 'Cipla', cat),
        ]

        # ── Neurology / Psychiatry ─────────────────────────────────────
        cat = 'Neurology/Psychiatry'
        items += [
            m('Alprazolam 0.25mg', 'Alprazolam', 'Tab', 'Pfizer', cat),
            m('Alprazolam 0.5mg', 'Alprazolam', 'Tab', 'Pfizer', cat),
            m('Alprazolam 1mg', 'Alprazolam', 'Tab', 'Pfizer', cat),
            m('Alprax 0.5mg', 'Alprazolam', 'Tab', 'Torrent', cat),
            m('Restyl 0.5mg', 'Alprazolam', 'Tab', 'Sun Pharma', cat),
            m('Clonazepam 0.25mg', 'Clonazepam', 'Tab', 'Roche', cat),
            m('Clonazepam 0.5mg', 'Clonazepam', 'Tab', 'Roche', cat),
            m('Clonazepam 1mg', 'Clonazepam', 'Tab', 'Roche', cat),
            m('Clonazepam 2mg', 'Clonazepam', 'Tab', 'Roche', cat),
            m('Rivotril 0.5mg', 'Clonazepam', 'Tab', 'Roche', cat),
            m('Diazepam 2mg', 'Diazepam', 'Tab', 'Roche', cat),
            m('Diazepam 5mg', 'Diazepam', 'Tab', 'Roche', cat),
            m('Diazepam 10mg', 'Diazepam', 'Tab', 'Roche', cat),
            m('Valium 5mg', 'Diazepam', 'Tab', 'Roche', cat),
            m('Calmpose 5mg', 'Diazepam', 'Tab', 'Ranbaxy', cat),
            m('Escitalopram 5mg', 'Escitalopram', 'Tab', 'Lundbeck', cat),
            m('Escitalopram 10mg', 'Escitalopram', 'Tab', 'Lundbeck', cat),
            m('Escitalopram 20mg', 'Escitalopram', 'Tab', 'Lundbeck', cat),
            m('Nexito 10mg', 'Escitalopram', 'Tab', 'Sun Pharma', cat),
            m('Cipralex 10mg', 'Escitalopram', 'Tab', 'Lundbeck', cat),
            m('Sertraline 25mg', 'Sertraline', 'Tab', 'Pfizer', cat),
            m('Sertraline 50mg', 'Sertraline', 'Tab', 'Pfizer', cat),
            m('Sertraline 100mg', 'Sertraline', 'Tab', 'Pfizer', cat),
            m('Zoloft 50mg', 'Sertraline', 'Tab', 'Pfizer', cat),
            m('Serta 50mg', 'Sertraline', 'Tab', 'Sun Pharma', cat),
            m('Fluoxetine 10mg', 'Fluoxetine', 'Cap', 'Eli Lilly', cat),
            m('Fluoxetine 20mg', 'Fluoxetine', 'Cap', 'Eli Lilly', cat),
            m('Prodep 20mg', 'Fluoxetine', 'Cap', 'Sun Pharma', cat),
            m('Fludac 20mg', 'Fluoxetine', 'Cap', 'Cadila', cat),
            m('Amitriptyline 10mg', 'Amitriptyline', 'Tab', 'Merck', cat),
            m('Amitriptyline 25mg', 'Amitriptyline', 'Tab', 'Merck', cat),
            m('Amitriptyline 75mg', 'Amitriptyline', 'Tab', 'Merck', cat),
            m('Tryptomer 10mg', 'Amitriptyline', 'Tab', 'Merck', cat),
            m('Duloxetine 20mg', 'Duloxetine', 'Cap', 'Eli Lilly', cat),
            m('Duloxetine 30mg', 'Duloxetine', 'Cap', 'Eli Lilly', cat),
            m('Duloxetine 60mg', 'Duloxetine', 'Cap', 'Eli Lilly', cat),
            m('Cymbalta 30mg', 'Duloxetine', 'Cap', 'Eli Lilly', cat),
            m('Duvanta 30mg', 'Duloxetine', 'Cap', 'Intas', cat),
            m('Pregabalin 75mg', 'Pregabalin', 'Cap', 'Pfizer', cat),
            m('Pregabalin 150mg', 'Pregabalin', 'Cap', 'Pfizer', cat),
            m('Lyrica 75mg', 'Pregabalin', 'Cap', 'Pfizer', cat),
            m('Gabapentin 100mg', 'Gabapentin', 'Cap', 'Parke-Davis', cat),
            m('Gabapentin 300mg', 'Gabapentin', 'Cap', 'Parke-Davis', cat),
            m('Gabaneuron 300mg', 'Gabapentin', 'Cap', 'Intas', cat),
            m('Phenytoin 100mg', 'Phenytoin', 'Tab', 'Pfizer', cat),
            m('Eptoin 100mg', 'Phenytoin', 'Tab', 'Abbott', cat),
            m('Valproate 200mg', 'Sodium Valproate', 'Tab', 'Sanofi', cat),
            m('Valproate 500mg', 'Sodium Valproate', 'Tab', 'Sanofi', cat),
            m('Valparin 200mg', 'Sodium Valproate', 'Tab', 'Sanofi', cat),
            m('Depakote 500mg', 'Valproic Acid', 'Tab', 'Abbott', cat),
            m('Levetiracetam 500mg', 'Levetiracetam', 'Tab', 'UCB', cat),
            m('Levetiracetam 1000mg', 'Levetiracetam', 'Tab', 'UCB', cat),
            m('Keppra 500mg', 'Levetiracetam', 'Tab', 'UCB', cat),
            m('Donepezil 5mg', 'Donepezil', 'Tab', 'Eisai', cat),
            m('Donepezil 10mg', 'Donepezil', 'Tab', 'Eisai', cat),
            m('Aricept 5mg', 'Donepezil', 'Tab', 'Eisai', cat),
            m('Memantine 5mg', 'Memantine', 'Tab', 'Merz', cat),
            m('Memantine 10mg', 'Memantine', 'Tab', 'Merz', cat),
            m('Namenda 10mg', 'Memantine', 'Tab', 'Forest Labs', cat),
        ]

        # ── Dermatology ────────────────────────────────────────────────
        cat = 'Dermatology'
        items += [
            m('Clobetasol cream 0.05%', 'Clobetasol Propionate', 'Cream', 'GlaxoSmithKline', cat),
            m('Tenovate cream', 'Clobetasol Propionate', 'Cream', 'GlaxoSmithKline', cat),
            m('Dermovate cream', 'Clobetasol Propionate', 'Cream', 'GlaxoSmithKline', cat),
            m('Betamethasone cream (Betnovate)', 'Betamethasone', 'Cream', 'GlaxoSmithKline', cat),
            m('Clotrimazole cream (Canesten)', 'Clotrimazole', 'Cream', 'Bayer', cat),
            m('Candid cream', 'Clotrimazole', 'Cream', 'Glenmark', cat),
            m('Miconazole cream', 'Miconazole', 'Cream', 'Janssen', cat),
            m('Ketoconazole cream', 'Ketoconazole', 'Cream', 'Janssen', cat),
            m('Ketoconazole shampoo', 'Ketoconazole', 'Shampoo', 'Janssen', cat),
            m('Tretinoin cream 0.025% (Retino-A)', 'Tretinoin', 'Cream', 'Janssen', cat),
            m('Tretinoin cream 0.05%', 'Tretinoin', 'Cream', 'Janssen', cat),
            m('Adapalene 0.1% gel (Deriva-MS)', 'Adapalene', 'Gel', 'Galderma', cat),
            m('Azelaic acid 15% gel', 'Azelaic Acid', 'Gel', 'Bayer', cat),
            m('Mupirocin ointment (Bactroban)', 'Mupirocin', 'Ointment', 'GlaxoSmithKline', cat),
            m('Permethrin 5% cream (Scaboma)', 'Permethrin', 'Cream', 'Omega', cat),
            m('Tacrolimus ointment 0.03% (Protopic)', 'Tacrolimus', 'Ointment', 'Astellas', cat),
            m('Tacrolimus ointment 0.1%', 'Tacrolimus', 'Ointment', 'Astellas', cat),
        ]

        # ── Ophthalmology ──────────────────────────────────────────────
        cat = 'Ophthalmology'
        items += [
            m('Chloramphenicol eye drops', 'Chloramphenicol', 'Drops', 'Nicholas Piramal', cat),
            m('Ciprofloxacin eye drops', 'Ciprofloxacin', 'Drops', 'Cipla', cat),
            m('Tobramycin eye drops', 'Tobramycin', 'Drops', 'Alcon', cat),
            m('Timolol 0.5% eye drops', 'Timolol Maleate', 'Drops', 'Merck', cat),
            m('Latanoprost 0.005% eye drops', 'Latanoprost', 'Drops', 'Pfizer', cat),
            m('Tropicamide 0.5% eye drops', 'Tropicamide', 'Drops', 'Alcon', cat),
            m('Tropicamide 1% eye drops', 'Tropicamide', 'Drops', 'Alcon', cat),
            m('Artificial tears (Refresh tears)', 'Carboxymethylcellulose', 'Drops', 'Allergan', cat),
            m('Systane eye drops', 'Polyethylene Glycol', 'Drops', 'Alcon', cat),
        ]

        # ── Urology ────────────────────────────────────────────────────
        cat = 'Urology'
        items += [
            m('Tamsulosin 0.4mg (Urimax)', 'Tamsulosin', 'Cap', 'Cipla', cat),
            m('Dutasteride 0.5mg (Avodart)', 'Dutasteride', 'Cap', 'GlaxoSmithKline', cat),
            m('Finasteride 5mg (Proscar)', 'Finasteride', 'Tab', 'MSD', cat),
            m('Solifenacin 5mg (Vesicare)', 'Solifenacin', 'Tab', 'Astellas', cat),
            m('Solifenacin 10mg', 'Solifenacin', 'Tab', 'Astellas', cat),
            m('Sildenafil 25mg', 'Sildenafil', 'Tab', 'Pfizer', cat),
            m('Sildenafil 50mg', 'Sildenafil', 'Tab', 'Pfizer', cat),
            m('Sildenafil 100mg', 'Sildenafil', 'Tab', 'Pfizer', cat),
            m('Penegra 50mg', 'Sildenafil', 'Tab', 'Zydus', cat),
            m('Tadalafil 5mg', 'Tadalafil', 'Tab', 'Eli Lilly', cat),
            m('Tadalafil 10mg', 'Tadalafil', 'Tab', 'Eli Lilly', cat),
            m('Tadalafil 20mg', 'Tadalafil', 'Tab', 'Eli Lilly', cat),
            m('Tadacip 20mg', 'Tadalafil', 'Tab', 'Cipla', cat),
        ]

        # ── GI / Laxatives ─────────────────────────────────────────────
        cat = 'GI/Laxative'
        items += [
            m('Lactulose syrup (Duphalac)', 'Lactulose', 'Syp', 'Abbott', cat),
            m('Bisacodyl 5mg (Dulcolax)', 'Bisacodyl', 'Tab', 'Boehringer Ingelheim', cat),
            m('Psyllium husk (Isabgol)', 'Ispaghula Husk', 'Powder', 'P&G', cat),
            m('Metamucil', 'Psyllium Husk', 'Powder', 'P&G', cat),
            m('Dicyclomine 10mg', 'Dicyclomine', 'Tab', 'Alkem', cat),
            m('Dicyclomine 20mg', 'Dicyclomine', 'Tab', 'Alkem', cat),
            m('Cyclopam 10mg', 'Dicyclomine', 'Tab', 'Indoco', cat),
            m('Hyoscine 10mg (Buscopan)', 'Hyoscine Butylbromide', 'Tab', 'Boehringer Ingelheim', cat),
            m('Mesalamine 400mg', 'Mesalamine', 'Tab', 'Sun Pharma', cat),
            m('Mesalamine 800mg', 'Mesalamine', 'Tab', 'Sun Pharma', cat),
            m('Mesacol 400mg', 'Mesalamine', 'Tab', 'Sun Pharma', cat),
            m('Sulfasalazine 500mg', 'Sulfasalazine', 'Tab', 'Pfizer', cat),
        ]

        total = len(items)
        MedicineCatalog.objects.bulk_create(items, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(f'Seeded {total} medicines into MedicineCatalog.'))
