import hashlib
import random
from django.core.management.base import BaseCommand
from accounts.models import ClinicAIExecutive

MALE_NAMES = [
    'Rajesh Kumar', 'Amit Singh', 'Suresh Yadav', 'Vikram Sharma', 'Arun Verma',
    'Deepak Gupta', 'Sanjay Mishra', 'Mohit Joshi', 'Ravi Tiwari', 'Pradeep Saxena',
    'Ramesh Pandey', 'Ajay Yadav', 'Vijay Singh', 'Manoj Shukla', 'Santosh Dubey',
    'Prakash Srivastava', 'Dinesh Chauhan', 'Rakesh Kumar', 'Naresh Chandra', 'Ashok Agarwal',
    'Pankaj Sharma', 'Rohit Verma', 'Gaurav Gupta', 'Neeraj Tripathi', 'Abhishek Rai',
    'Rahul Srivastava', 'Ankit Singh', 'Vivek Pandey', 'Harish Chandra', 'Vinod Kumar',
    'Saurabh Mishra', 'Akhilesh Yadav', 'Devendra Singh', 'Omkar Sharma', 'Pramod Tiwari',
    'Umesh Gupta', 'Arvind Kumar', 'Dilip Saxena', 'Kamlesh Verma', 'Narendra Pal',
    'Karthik Rajput', 'Balaji Sharma', 'Venkat Rao', 'Arjun Bajpai', 'Tarun Agarwal',
]

FEMALE_NAMES = [
    'Priya Sharma', 'Sunita Devi', 'Rekha Singh', 'Geeta Verma', 'Anita Gupta',
    'Kavita Mishra', 'Seema Yadav', 'Neha Tiwari', 'Pooja Pandey', 'Meena Saxena',
    'Sushma Chandra', 'Usha Dubey', 'Rashmi Srivastava', 'Swati Sharma', 'Deepa Agarwal',
    'Asha Kumar', 'Nirmala Singh', 'Savita Verma', 'Vandana Rai', 'Shobha Tripathi',
    'Ritu Gupta', 'Divya Shukla', 'Sarika Bajpai', 'Namrata Joshi', 'Preeti Chauhan',
]

# North India focused: UP, NCR/Delhi, MP, Rajasthan, Haryana, Uttarakhand, Bihar
CITIES_BY_STATE = [
    # Uttar Pradesh (heavy focus)
    ('Lucknow', 'Uttar Pradesh'),
    ('Lucknow', 'Uttar Pradesh'),
    ('Kanpur', 'Uttar Pradesh'),
    ('Kanpur', 'Uttar Pradesh'),
    ('Agra', 'Uttar Pradesh'),
    ('Agra', 'Uttar Pradesh'),
    ('Varanasi', 'Uttar Pradesh'),
    ('Varanasi', 'Uttar Pradesh'),
    ('Prayagraj', 'Uttar Pradesh'),
    ('Prayagraj', 'Uttar Pradesh'),
    ('Gorakhpur', 'Uttar Pradesh'),
    ('Gorakhpur', 'Uttar Pradesh'),
    ('Bareilly', 'Uttar Pradesh'),
    ('Bareilly', 'Uttar Pradesh'),
    ('Meerut', 'Uttar Pradesh'),
    ('Meerut', 'Uttar Pradesh'),
    ('Mathura', 'Uttar Pradesh'),
    ('Aligarh', 'Uttar Pradesh'),
    ('Moradabad', 'Uttar Pradesh'),
    ('Saharanpur', 'Uttar Pradesh'),
    ('Muzaffarnagar', 'Uttar Pradesh'),
    ('Firozabad', 'Uttar Pradesh'),
    ('Ghaziabad', 'Uttar Pradesh'),
    ('Noida', 'Uttar Pradesh'),
    ('Greater Noida', 'Uttar Pradesh'),
    ('Lakhimpur', 'Uttar Pradesh'),
    ('Shahjahanpur', 'Uttar Pradesh'),
    ('Jhansi', 'Uttar Pradesh'),
    # Delhi NCR
    ('New Delhi', 'Delhi'),
    ('New Delhi', 'Delhi'),
    ('Delhi', 'Delhi'),
    ('Delhi', 'Delhi'),
    ('Gurgaon', 'Haryana'),
    ('Gurgaon', 'Haryana'),
    ('Faridabad', 'Haryana'),
    ('Noida', 'Uttar Pradesh'),
    ('Dwarka', 'Delhi'),
    ('Rohini', 'Delhi'),
    ('Pitampura', 'Delhi'),
    # Madhya Pradesh
    ('Bhopal', 'Madhya Pradesh'),
    ('Bhopal', 'Madhya Pradesh'),
    ('Indore', 'Madhya Pradesh'),
    ('Indore', 'Madhya Pradesh'),
    ('Gwalior', 'Madhya Pradesh'),
    ('Jabalpur', 'Madhya Pradesh'),
    ('Ujjain', 'Madhya Pradesh'),
    ('Sagar', 'Madhya Pradesh'),
    ('Rewa', 'Madhya Pradesh'),
    ('Satna', 'Madhya Pradesh'),
    # Rajasthan
    ('Jaipur', 'Rajasthan'),
    ('Jaipur', 'Rajasthan'),
    ('Jodhpur', 'Rajasthan'),
    ('Kota', 'Rajasthan'),
    ('Ajmer', 'Rajasthan'),
    ('Bikaner', 'Rajasthan'),
    ('Alwar', 'Rajasthan'),
    # Haryana
    ('Rohtak', 'Haryana'),
    ('Hisar', 'Haryana'),
    ('Panipat', 'Haryana'),
    ('Karnal', 'Haryana'),
    ('Ambala', 'Haryana'),
    # Bihar
    ('Patna', 'Bihar'),
    ('Patna', 'Bihar'),
    ('Gaya', 'Bihar'),
    ('Muzaffarpur', 'Bihar'),
    # Uttarakhand
    ('Dehradun', 'Uttarakhand'),
    ('Haridwar', 'Uttarakhand'),
    # Punjab
    ('Ludhiana', 'Punjab'),
    ('Amritsar', 'Punjab'),
    ('Chandigarh', 'Punjab'),
]


class Command(BaseCommand):
    help = 'Create sample approved executives for the Executive Network page'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete existing sample executives (no photo) and recreate',
        )

    def handle(self, *args, **options):
        if options['reset']:
            deleted, _ = ClinicAIExecutive.objects.filter(
                status='approved', photo=''
            ).delete()
            self.stdout.write(f'Deleted {deleted} existing sample executives.')

        existing = ClinicAIExecutive.objects.filter(status='approved').count()
        if existing >= 67:
            self.stdout.write(self.style.WARNING(
                f'Already {existing} approved executives. Use --reset to recreate.'
            ))
            return

        rng = random.Random(42)

        all_names = [(n, 'M') for n in MALE_NAMES] + [(n, 'F') for n in FEMALE_NAMES]
        rng.shuffle(all_names)

        used_mobiles = set(ClinicAIExecutive.objects.values_list('mobile', flat=True))
        mobiles = []
        while len(mobiles) < 67:
            prefix = rng.choice(['7', '8', '9'])
            rest = ''.join([str(rng.randint(0, 9)) for _ in range(9)])
            mob = prefix + rest
            if mob not in used_mobiles:
                used_mobiles.add(mob)
                mobiles.append(mob)

        created = 0
        for i in range(67):
            name, gender = all_names[i % len(all_names)]
            city, state = rng.choice(CITIES_BY_STATE)
            mobile = mobiles[i]

            while True:
                first = str(rng.randint(2, 9))
                rest_digits = ''.join([str(rng.randint(0, 9)) for _ in range(11)])
                aadhaar = first + rest_digits
                if len(set(aadhaar)) > 1:
                    break

            ClinicAIExecutive.objects.create(
                name=name,
                gender=gender,
                mobile=mobile,
                city=city,
                state=state,
                aadhaar_last4=aadhaar[-4:],
                aadhaar_hash=hashlib.sha256(aadhaar.encode()).hexdigest(),
                status='approved',
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Created {created} sample executives.'
        ))
