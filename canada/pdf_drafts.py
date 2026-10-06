"""Create editable XFA drafts from pinned templates, never submission-ready PDFs.

Only explicitly mapped scalar values are written. The accompanying report lists
all populated case fields not exported, plus intake issues. Dataset locators are
absolute within xfa:data and use explicit 1-based sibling indexes where repeated.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET

import pymupdf as fitz

from .review import editable_fields
from .official_options import REPRESENTATIVE_ACTIONS, REPRESENTATIVE_CATEGORIES
from .preparation import prepare_case, ordered_activities, date_value, is_confirmed
from .value_translation import translate

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
DATA = '{http://www.xfa.org/schema/xfa-data/1.0/}data'
FORMS = ('IMM5257', 'IMM5707', 'IMM5476')


def packets(doc):
    kind, value = doc.xref_get_key(doc.pdf_catalog(), 'AcroForm/XFA')
    if kind != 'array':
        raise ValueError('Expected an XFA packet array')
    refs = re.findall(r'\(([^)]*)\)\s*(\d+)\s+\d+\s+R', value)
    if len({n for n, _ in refs}) != len(refs):
        raise ValueError('Duplicate XFA packets')
    return {name: (i, int(ref)) for i, (name, ref) in enumerate(refs)}


def iso_date(value):
    for pattern in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            result = datetime.strptime(value.strip(), pattern).date()
            return result.isoformat()
        except ValueError:
            pass
    raise ValueError('Use YYYY-MM-DD or DD/MM/YYYY')


def _resolve(root, path):
    nodes = root.findall(path)
    if len(nodes) != 1:
        raise ValueError(f'Expected exactly one dataset target: {path}')
    return nodes[0]


def _plan(case, form, data, datasets):
    values = editable_fields(case)
    writes, issues = [], []

    def add(source, target, transform=None):
        value = values.get(source, '').strip()
        if not value:
            return
        if any(ord(char) < 32 and char not in '\t\n\r' for char in value):
            issues.append({'source':source,'reason':'Invalid XML control character; correct the source value before export'})
            return
        try:
            result = transform(value) if transform else value
            if form == 'IMM5257':
                # Pinned form scripts accept English/French characters only.
                # Keep supported French accents; decompose other Latin accents
                # such as the í in Brasília. Never mutate the stored source.
                french = 'ÀÂÄÆÇÉÈÊËÎÏÔÖŒÙÛÜŸàâäæçéèêëîïôöœùûüÿ'
                punctuation = {'–':'-','—':'-','’':"'",'‘':"'",'“':'"','”':'"','\u00a0':' '}
                normalized = []
                for char in result:
                    if ord(char) < 128 or char in french:
                        normalized.append(char)
                    elif char in punctuation:
                        normalized.append(punctuation[char])
                    elif 'LATIN' in unicodedata.name(char,''):
                        folded = ''.join(c for c in unicodedata.normalize('NFKD',char) if not unicodedata.combining(c))
                        if not folded.isascii():
                            raise ValueError('Confirm an English/French spelling accepted by IMM5257')
                        normalized.append(folded)
                    else:
                        raise ValueError('Confirm an English/French spelling accepted by IMM5257')
                result = ''.join(normalized)
        except ValueError as error:
            issues.append({'source': source, 'reason': str(error)})
            return
        _resolve(data, target)
        writes.append({'source': source, 'dataset_path': target, 'value': result,
                       'transformation': 'official format/choice or English-French character normalization' if result != value else 'verbatim'})

    def fields(prefix, pairs):
        for source, target in pairs.items():
            add(source, prefix + target)

    def date_parts(source, prefix, names):
        for i, name in enumerate(names):
            add(source, prefix + name, lambda v, index=i: iso_date(v).split('-')[index])

    def choice(source, target, list_name):
        def convert(value):
            value = translate(value,list_name)
            entries = datasets.findall('LOVFile/LOV/'+list_name+'/*')
            matches = []
            for entry in entries:
                label = (entry.text or '').strip()
                labels = {label.casefold(), (entry.get('lic') or '').casefold()}
                # The passport list uses e.g. "BRA (Brazil)". Accept the exact
                # country label inside that wrapper only when the match is unique.
                wrapped = re.fullmatch(r'[A-Z]{3} \((.+)\)', label)
                if wrapped:
                    labels.add(label[:3].casefold())
                    labels.add(wrapped[1].casefold())
                if value.casefold() in labels:
                    matches.append(entry.get('lic'))
            if len(matches) != 1 or not matches[0]:
                raise ValueError('Select the exact English option from the official form; no country/language/sex is inferred')
            return matches[0]
        add(source, target, convert)

    def yesno(value):
        codes = {'yes':'Y','sim':'Y','no':'N','não':'N','nao':'N'}
        if value.casefold() not in codes:
            raise ValueError('Expected explicit yes/no answer to the complete official question')
        return codes[value.casefold()]

    if form == 'IMM5257':
        p = 'form1/Page1/PersonalDetails/'
        fields(p, {'identity.family_name': 'Name/FamilyName',
                   'identity.given_names': 'Name/GivenName',
                   'identity.city_of_birth': 'PlaceBirthCity',
                   'staff_review.uci': 'UCIClientID'})
        date_parts('identity.date_of_birth', p, ('DOBYear', 'DOBMonth', 'DOBDay'))
        for source, target, options in (
            ('identity.sex','Sex/Sex','GenderMelList'),
            ('identity.birth_country','PlaceBirthCountry','CountryOfBirthList'),
            ('identity.nationality','Citizenship/Citizenship','CountryOfCitizenshipList'),
            ('staff_review.service_language','ServiceIn/ServiceIn','PreferenceLanguageList'),
            ('identity.residence_country','CurrentCOR/Row2/Country','CountryOfLastPermanentResidentList'),
            ('identity.residence_status','CurrentCOR/Row2/Status','ImmigrationStatusList')):
            choice(source,p+target,options)
        add('official_review.previous_residence_over_six_months',p+'PCRIndicator',yesno)
        add('official_review.applying_from_residence_country',p+'SameAsCORIndicator',yesno)
        confirmed = [(i,r) for i,r in enumerate(case.residence_records) if is_confirmed(r)]
        if case.official_review.previous_residence_over_six_months.casefold() in ('yes','sim'):
            for slot,(i,record) in enumerate(confirmed[:2],2):
                source = f'residence_records[{i}].'
                dest = p+f'PreviousCOR/Row{slot}/'
                choice(source+'country',dest+'Country','CountryOfBirthList')
                choice(source+'status_or_purpose',dest+'Status','ImmigrationStatusList')
                for key,node in (('start_date','FromDate'),('end_date','ToDate')):
                    add(source+key,dest+node,iso_date)
                    date_parts(source+key,p+f'PCRDatesR{slot-1}/',
                               ('FromYr','FromMM','FromDD') if key=='start_date' else ('ToYr','ToMM','ToDD'))
        elif confirmed:
            issues.append({'source':'official_review.previous_residence_over_six_months','reason':'Confirmed residence records exist; verify the official six-month question. Records are preserved in the supplementary sheet.'})
        choice('identity.marital_status','form1/Page1/MaritalStatus/SectionA/MaritalStatus','MaritalStatusList')
        fields('form1/Page1/MaritalStatus/SectionA/', {
            'relationships.spouse_family_name': 'FamilyName',
            'relationships.spouse_given_names': 'GivenName'})
        add('relationships.marriage_start_date','form1/Page1/MaritalStatus/SectionA/DateOfMarriage',iso_date)
        p = 'form1/Page2/MaritalStatus/SectionA/'
        choice('staff_review.native_language',p+'Languages/languages/nativeLang/nativeLang','ContactLanguageList')
        fields(p, {'relationships.former_spouse_family_name': 'PMFamilyName',
                   'relationships.former_spouse_given_names': 'GivenName/PMGivenName',
                   'passport.number': 'Passport/PassportNum/PassportNum'})
        add('relationships.has_previous_relationship',p+'PrevMarriedIndicator',yesno)
        date_parts('relationships.former_spouse_date_of_birth',p+'PrevSpouseDOB/',('DOBYear','DOBMonth','DOBDay'))
        add('relationships.previous_start_date',p+'FromDate',iso_date)
        add('relationships.previous_end_date',p+'ToDate/ToDate',iso_date)
        choice('relationships.previous_relationship_type',p+'TypeOfRelationship','MaritalStatusHistoryList')
        add('passport.issue_date', p+'Passport/IssueDate/IssueDate', iso_date)
        add('passport.expiry_date', p+'Passport/ExpiryDate', iso_date)
        choice('passport.issuing_country',p+'Passport/CountryofIssue/CountryofIssue','CountryTravelDocumentList')
        date_parts('passport.issue_date', p+'Passport/', ('IssueYYYY', 'IssueMM', 'IssueDD'))
        date_parts('passport.expiry_date', p+'Passport/', ('expiryYYYY', 'expiryMM', 'expiryDD'))
        # Full Brasília-style addresses are retained for review, never split by guessing.
        fields('form1/Page2/ContactInformation/contact/', {
            'contact.email': 'FaxEmail/Email',
            'contact.city': 'ResidentialAddressRow1/CityTown/CityTown',
            'contact.postcode': 'ResidentialAddressRow2/PostalCode/PostalCode'})
        c = 'form1/Page2/ContactInformation/contact/'
        if not case.official_review.residential_street_name.strip() and case.contact.address.strip():
            # The intake supplies one complete address, not inferred components.
            # Preserve it as a draft fallback within the pinned 100-character field.
            add('contact.address', c+'ResidentialAddressRow1/StreetName/Streetname',
                lambda value: value if len(value) <= 100 else 'See residential address in continuation sheet')
            issues.append({'source':'contact.address','reason':'Complete source address used as draft street-line fallback (or continuation reference above 100 characters). Review official street/unit/number components and visible fit in Acrobat; no address splitting was performed.'})
        fields(c, {
            'official_review.residential_unit':'ResidentialAddressRow1/AptUnit/AptUnit',
            'official_review.residential_street_number':'ResidentialAddressRow1/StreetNum/StreetNum',
            'official_review.residential_street_name':'ResidentialAddressRow1/StreetName/Streetname',
            'official_review.mailing_po_box':'AddressRow1/POBox/POBox',
            'official_review.mailing_unit':'AddressRow1/Apt/AptUnit',
            'official_review.mailing_street_number':'AddressRow1/StreetNum/StreetNum',
            'official_review.mailing_street_name':'AddressRow1/Streetname/Streetname',
            'official_review.mailing_city':'AddressRow2/CityTow/CityTown',
            'official_review.mailing_postcode':'AddressRow2/PostalCode/PostalCode'})
        choice('contact.country',c+'ResidentialAddressRow2/Country/Country','CountryOfBirthList')
        choice('official_review.mailing_country',c+'AddressRow2/Country/Country','CountryOfBirthList')
        # The template's province dropdown is Canadian. Do not insert a Brazilian
        # state abbreviation into it, even when the intake explicitly supplies DF.
        if case.contact.country.strip().casefold() in ('canada','511'):
            choice('contact.state',c+'ResidentialAddressRow2/ProvinceState/ProvinceState','ProvinceAbbrevList')
        if case.official_review.mailing_country.strip().casefold() in ('canada','511'):
            choice('official_review.mailing_province',c+'AddressRow2/ProvinceState/ProvinceState','ProvinceAbbrevList')
        add('contact.mailing_same_as_residential',c+'SameAsMailingIndicator',yesno)
        p = 'form1/Page3/DetailsOfVisit/'
        choice('trip.purpose',p+'PurposeRow1/PurposeOfVisit/PurposeOfVisit','VisitPurposeList')
        fields(p, {'trip.host_name': 'Contacts_Row1/Name/Name',
                   'trip.host_address': 'Contacts_Row1/AddressInCanada/AddressInCanada',
                   'trip.relationship': 'Contacts_Row1/RelationshipToMe/RelationshipToMe'})
        def funds(value):
            if not re.fullmatch(r'\d+(?:\.\d{1,2})?', value):
                raise ValueError('Enter available CAD funds as digits with optional decimal point')
            return value
        add('trip.available_funds_cad', p+'PurposeRow1/Funds/Funds', funds)
        for source, node in (('trip.arrival_date','FromDate'), ('trip.departure_date','ToDate')):
            add(source, p+'PurposeRow1/HowLongStay/'+node, iso_date)
        fields('form1/Page3/Education/Edu_Row1/', {
            'education.course': 'FieldOfStudy', 'education.institution': 'School',
            'education.city': 'CityTown'})
        choice('education.country','form1/Page3/Education/Edu_Row1/Country/Country','CountryOfBirthList')
        add('official_review.post_secondary_education','form1/Page3/Education/EducationIndicator',yesno)
        for source,year,month in (('start_date','FromYear','FromMonth'),('end_date','ToYear','ToMonth')):
            add('education.'+source,'form1/Page3/Education/Edu_Row1/'+year,lambda v:date_value(v)[:4])
            add('education.'+source,'form1/Page3/Education/Edu_Row1/'+month,lambda v:date_value(v)[5:7])
        for slot, (i, activity) in enumerate(ordered_activities(case)[:3],1):
            p = f'form1/Page3/Occupation/OccupationRow{slot}/'
            fields(p, {f'activities[{i}].position':'Occupation/Occupation',
                       f'activities[{i}].organization':'Employer',
                       f'activities[{i}].city':'CityTown/CityTown'})
            choice(f'activities[{i}].country',p+'Country/Country','CountryOfBirthList')
            if activity.country.strip().casefold() in ('canada','511'):
                choice(f'activities[{i}].state',p+'ProvState','ProvinceAbbrevList')
            for source, year, month in (('start_date','FromYear','FromMonth'), ('end_date','ToYear','ToMonth')):
                if source == 'end_date' and activity.ongoing_answer.strip().lower() not in ('no','não','nao'):
                    issues.append({'source':f'activities[{i}].end_date','reason':'End date withheld until the period is explicitly confirmed as finished; ongoing/unknown periods require review.'})
                    continue
                add(f'activities[{i}].{source}', p+year, lambda v: date_value(v)[:4])
                add(f'activities[{i}].{source}', p+month, lambda v: date_value(v)[5:7])
        if len(ordered_activities(case)) > 3:
            issues.append({'source':'activities', 'reason':'IMM5257 has 3 rows; additional activities are included in IMM5257-CONTINUATION-DRAFT.pdf. Review the attachment with the official form.'})
        for source,target in {
            'tuberculosis_or_close_contact_last_two_years':'BackgroundInfo/Choice[1]',
            'disorder_requiring_social_or_health_services':'BackgroundInfo/Choice[2]',
            'canada_overstay_unauthorized_work_or_study':'BackgroundInfo2/VisaChoice1',
            'visa_refusal_denied_entry_or_removal_any_country':'BackgroundInfo2/VisaChoice2',
            'previously_applied_to_enter_or_remain_canada':'BackgroundInfo2/Details/VisaChoice3',
            'committed_arrested_charged_or_convicted_any_country':'PageWrapper/BackgroundInfo3/Choice',
            'military_militia_civil_defence_security_or_police':'PageWrapper/Military/Choice',
            'associated_with_violent_or_criminal_organization':'PageWrapper/Occupation/Choice',
            'witnessed_or_participated_in_ill_treatment_looting_desecration':'PageWrapper/GovPosition/Choice'}.items():
            add('official_review.'+source,'form1/Page3/'+target,yesno)
        fields('form1/Page3/',{
            'official_review.medical_details':'BackgroundInfo/Details/MedicalDetails',
            'official_review.immigration_explanation':'BackgroundInfo2/Details/refusedDetails',
            'official_review.criminal_details':'PageWrapper/BackgroundInfo3/details',
            'official_review.service_details':'PageWrapper/Military/militaryServiceDetails'})
    elif form == 'IMM5707':
        p = 'IMM_5707/page1/SectionA/'
        def marital(value):
            value = translate(value,'MaritalStatusList')
            # Pinned IMM5707 <items save="1"> values; not IMM5257's LOV codes.
            options = {'common-law':'1','single':'2','divorced':'3','annulled marriage':'4',
                       'married':'5','legally separated':'6','widowed':'7','unknown':'8'}
            if value.casefold() not in options:
                raise ValueError('Use an exact English IMM5707 marital-status option')
            return options[value.casefold()]
        fields(p+'Applicant/PaddedEntry/', {
            'identity.family_name':'PersonalData[1]/FamilyName',
            'identity.given_names':'PersonalData[1]/GivenNames',
            'identity.birth_country':'PersonalData[2]/COB',
            'employment.profession':'PersonalData[2]/Occupation'})
        add('identity.date_of_birth',p+'Applicant/PaddedEntry/PersonalData[2]/DOB',iso_date)
        add('identity.marital_status',p+'Applicant/PaddedEntry/PersonalData[2]/MaritalStatus',marital)
        fields(p+'Spouse/PaddedEntry/', {
            'relationships.spouse_family_name':'PersonalData[1]/FamilyName',
            'relationships.spouse_given_names':'PersonalData[1]/GivenNames',
            'relationships.spouse_birth_country':'PersonalData[2]/COB',
            'relationships.spouse_occupation':'PersonalData[2]/Occupation',
            'relationships.spouse_address':'PersonalData[2]/Address'})
        add('relationships.spouse_date_of_birth', p+'Spouse/PaddedEntry/PersonalData[2]/DOB', iso_date)
        def yesno(v):
            codes = {'yes':'1','sim':'1','no':'2','não':'2','nao':'2'}
            if v.lower() not in codes:
                raise ValueError('Expected explicit yes/no answer')
            return codes[v.lower()]
        add('relationships.spouse_accompanying_answer', p+'Spouse/PaddedEntry/Accompanying/yesno',yesno)
        # Template explicitly says PARENT 1/2 (MOTHER OR FATHER). Source order is
        # preserved; this does not assign motherhood, fatherhood or guardianship.
        for group, records in (('parents',case.family.parents),('children',case.family.children)):
            if group == 'parents' and len(records) > 2:
                raise ValueError('IMM5707 supports two parents; resolve extra parent records before export')
            if group == 'children':
                section = _resolve(data,'IMM_5707/page1/SectionB')
                prototype = section.find('Child')
                for _ in range(max(0,len(records)-len(section.findall('Child')))):
                    section.insert(list(section).index(section.find('Note2')),deepcopy(prototype))
            for i, member in enumerate(records):
                dest = p+f'Parent{i+1}/PaddedEntry/' if group=='parents' else f'IMM_5707/page1/SectionB/Child[{i+1}]/PaddedEntry/'
                src = f'family.{group}[{i}].'
                fields(dest, {src+'family_name':'PersonalData[1]/FamilyName',
                              src+'given_names':'PersonalData[1]/GivenNames',
                              src+'birth_country':'PersonalData[2]/COB',
                              src+'address':'PersonalData[2]/Address',
                              src+'occupation':'PersonalData[2]/Occupation'})
                add(src+'date_of_birth',dest+'PersonalData[1]/DOB',iso_date)
                add(src+'marital_status',dest+'PersonalData[2]/MaritalStatus',marital)
                add(src+'accompanying_answer',dest+'Accompanying/yesno',yesno)
                if group=='children':
                    add(src+'relationship',dest+'PersonalData[1]/Relationship')
    else:
        p = 'IMM_5476/Page1/SectionA/'
        fields(p, {'identity.family_name':'familyName','identity.given_names':'givenName',
                   'staff_review.uci':'UCI','contact.email':'office[1]'})
        add('identity.date_of_birth',p+'DOB',iso_date)
        action = case.representative.action.strip()
        if action and action not in REPRESENTATIVE_ACTIONS:
            issues.append({'source':'representative.action','reason':'Unknown action; select an explicit representative action in the review editor'})
            return writes, issues
        if action:
            add('representative.action','IMM_5476/Page1/RadioButtonList',lambda v: REPRESENTATIVE_ACTIONS[v])
        else:
            issues.append({'source':'representative.action','reason':'Appointment/update/cancellation/withdrawal action remains unconfirmed'})
        action_code = REPRESENTATIVE_ACTIONS.get(action, '')
        if action_code in ('3','4'):
            fields('IMM_5476/Page1/sectionC/',{
                'representative.cancelled_family_name':'familyName',
                'representative.cancelled_given_names':'givenName',
                'representative.cancelled_organization':'organization'})
            if not case.representative.cancelled_family_name.strip():
                issues.append({'source':'representative.cancelled_family_name','reason':'Identify the representative being cancelled separately from the new representative'})
        if action_code == '5':
            fields('IMM_5476/Page1/sectionD/',{
                'representative.family_name':'familyName',
                'representative.given_names':'givenName',
                'representative.organization':'organization'})
        if action_code in ('3','5'):
            issues.append({'source':'representative','reason':'Only the selected cancellation/withdrawal sections are populated. Review and sign manually.'})
            return writes, issues
        p = 'IMM_5476/Page1/SectionB/'
        fields(p, {'representative.family_name':'familyName','representative.given_names':'givenName'})
        fields(p+'question7/', {f'representative.{src}':target for src,target in {
            'organization':'organization','unit':'unit','street_number':'streetNo',
            'street_name':'streetName','city':'city','province':'province','country':'country',
            'postcode':'postalcode','phone_country_code':'phoneCountryCode',
            'phone_number':'phoneNumber','email':'email'}.items()})
        category = case.representative.category.strip()
        if category in REPRESENTATIVE_CATEGORIES:
            group, code, membership = REPRESENTATIVE_CATEGORIES[category]
            selection = 'uncompensated' if group == 'questionI' else 'compensated'
            add('representative.category',p+'question6/'+group+'/'+selection,lambda _:code)
            if membership:
                add('representative.membership_number',p+'question6/'+membership)
                if not case.representative.membership_number.strip():
                    issues.append({'source':'representative.membership_number','reason':'Confirm whether this professional category requires a membership number and enter it explicitly'})
            if category == 'Unpaid - other':
                add('representative.other_category_details',p+'question6/questionI/otherRep')
                if not case.representative.other_category_details.strip():
                    issues.append({'source':'representative.other_category_details','reason':'Describe the selected other representative category'})
            if 'law society' in category:
                province = 'questionI/province2' if group == 'questionI' else 'questionII/province'
                add('representative.membership_province',p+'question6/'+province)
                add('representative.supervising_lawyer',p+'question7/lawyer')
                add('representative.supervising_lawyer_membership',p+'question7/membershipID')
        else:
            issues.append({'source':'representative.category','reason':'Select the explicit paid/unpaid category; qualifications are never inferred from contact details'})
        issues.append({'source':'representative', 'reason':'Verify the selected action, paid/unpaid category, regulatory membership and declarations in Acrobat. Signatures and signature dates remain blank.'})
    return writes, issues


def generate_drafts(case, output_dir, template_dir=None):
    """Legacy entry point: retain intake preparation and private case support files."""
    return _generate_drafts(case, output_dir, template_dir, canonical_prepared=False)


def generate_prepared_drafts(case, output_dir, template_dir=None):
    """Mechanical generator entry for an already-ready canonical adapter value.

    This path deliberately skips legacy preparation, raw-source validation,
    review derivation and CanadaCase persistence.
    """
    return _generate_drafts(case, output_dir, template_dir, canonical_prepared=True)


def _generate_drafts(case, output_dir, template_dir=None, *, canonical_prepared):
    """Publish a new private bundle atomically; never overwrite existing files."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError('Choose a new output folder; existing files are never overwritten')
    case = deepcopy(case)
    if canonical_prepared:
        validation = None
    else:
        case = prepare_case(case)
        from .validation import ensure_generation_allowed
        validation = ensure_generation_allowed(case)
    template_dir = Path(template_dir or ROOT/'templates/canada')
    matrix = json.loads((ROOT/'canada/coverage_matrix.yaml').read_text())
    expected = {Path(v['file']).stem: v['sha256'] for v in matrix['templates'].values()}
    for name in FORMS:
        path = template_dir/f'{name}.pdf'
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
            raise ValueError(f'Template identity changed: {name}; review mappings first')
    report = {'format':'canada-xfa-draft-report','version':1,'submission_ready':False,
              'notice':'DRAFT. Open in desktop Adobe Acrobat. Review every field, complete unmapped information, validate where available, and sign manually. Browser/Preview renderers do not support these XFA forms.',
              'intake_issues':[] if canonical_prepared else case.validation_issues(),
              'validation_status':'VALID' if canonical_prepared else validation.status,
              'structured_issues':[] if canonical_prepared else [asdict(i) for i in validation.issues],
              'forms':{}}
    if canonical_prepared:
        report['review_tasks']=[]
        report['automated_answers']=[]
    else:
        from .review_tasks import review_tasks, automated_answers
        report['review_tasks']=[{'status':t.status,**asdict(t)} for t in review_tasks(case)]
        report['automated_answers']=automated_answers(case)
    staging = Path(tempfile.mkdtemp(prefix='.canada-draft-',dir=output_dir.parent))
    used = set()
    try:
        for name in FORMS:
            out = staging/f'{name}-DRAFT.pdf'
            shutil.copyfile(template_dir/f'{name}.pdf',out)
            os.chmod(out,0o600)
            with fitz.open(out) as doc:
                refs = packets(doc)
                index,xref = refs['datasets']
                original = doc.xref_stream(xref)
                root = ET.fromstring(original)
                data = root.find(DATA)
                if data is None:
                    raise ValueError('Missing XFA data')
                # Acrobat can display prefixed XHTML serialization as literal XML
                # in blank IMM5476 rich-text defaults. Normalize only whitespace-
                # only XHTML defaults in this hash-pinned template, not real text.
                for node in data.iter():
                    if any(child.tag == '{http://www.w3.org/1999/xhtml}body' for child in node):
                        if ''.join(node.itertext()).strip():
                            raise ValueError('Unexpected nonempty rich-text template default')
                        for child in list(node):
                            node.remove(child)
                        node.text = None
                writes,issues = _plan(case,name,data,root)
                for item in writes:
                    node = _resolve(data,item['dataset_path'])
                    # Replace rich-text default content, never its parent/siblings.
                    for child in list(node):
                        node.remove(child)
                    node.text = item['value']
                    used.add(item['source'])
                doc.update_stream(xref,ET.tostring(root,encoding='utf-8'))
                doc.saveIncr()
            with fitz.open(out) as check:
                reread = ET.fromstring(check.xref_stream(packets(check)['datasets'][1])).find(DATA)
                for item in writes:
                    if _resolve(reread,item['dataset_path']).text != item['value']:
                        raise ValueError('XFA round-trip verification failed')
            report['forms'][name] = {'template_sha256':expected[name],
                'packet':'datasets','packet_index':index,
                'source_packet_sha256':hashlib.sha256(original).hexdigest(),
                'writes':[{'source':w['source'],'dataset_path':w['dataset_path'],'transformation':w['transformation']} for w in writes],
                'issues':issues,'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest()}
        from .continuation import create_continuation
        report['preparation_issues'] = []  # Already represented by structured_issues/intake_issues
        report['continuation'] = create_continuation(
            case, staging/'IMM5257-CONTINUATION-DRAFT.pdf',
            omit_absent=canonical_prepared,
        )
        if report['continuation']:
            used.update(report['continuation']['sources'])
            report['continuation']['output_sha256'] = hashlib.sha256((staging/report['continuation']['file']).read_bytes()).hexdigest()
        report['populated_fields_not_exported'] = sorted(k for k,v in editable_fields(case).items() if v.strip() and k not in used)
        (staging/'review-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        review = ['# Canada draft review', '', report['notice'], '', '## Intake issues', '']
        if not canonical_prepared:
            from .review_tasks import task_text, review_tasks
            review.extend(task_text(t)+'\n' for t in review_tasks(case))
        review.extend('- '+issue for issue in report['preparation_issues'])
        for name, form_report in report['forms'].items():
            review.extend(['', '## '+name, '', f"{len(form_report['writes'])} dataset values written and reopened successfully.", ''])
            review.extend('- '+issue['source']+': '+issue['reason'] for issue in form_report['issues'])
        review.extend(['', '## Populated case fields not exported', '',
                       'Some fields support letters or internal review instead of these forms. Others require manual completion. Consult the saved source case; no answer has been discarded.', ''])
        review.extend('- '+path for path in report['populated_fields_not_exported'])
        review.extend(['', '## Mandatory final review', '',
            '- Check every official question, including empty required and conditional fields.',
            '- Confirm addresses, phone numbers, residence periods, marital status, immigration/background answers and representative authorization.',
            '- Review the generated continuation sheet, if present, including unresolved activity fields and confirmed history.',
            '- Review XFA scripts and layout in desktop Acrobat. XML round-trip verification alone does not validate visible fields.',
            '- Run official validation where available. Signatures, consents and validation barcodes are never generated by this app.', ''])
        (staging/'review-checklist.md').write_text('\n'.join(review),encoding='utf-8')
        (staging/'READ-ME.txt').write_text(report['notice']+'\n\nSee review-report.json for limitations and fields not exported. No signatures, consents, validation flags or barcodes were created.\n')
        if not canonical_prepared:
            # The legacy desktop workflow keeps its historical private support file.
            from .case_store import save_case
            save_case(case,staging/'source.canada-case.json')
        if output_dir.exists():
            raise ValueError('Output folder was created concurrently')
        staging.rename(output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return report


if __name__ == '__main__':
    import argparse
    from .case_store import load_case
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path,help='New, non-existing directory')
    args = parser.parse_args()
    generate_drafts(load_case(args.case),args.output)
    print('Created drafts and review checklist in '+str(args.output))
