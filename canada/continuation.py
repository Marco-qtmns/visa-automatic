"""Paginated supplementary sheets, separate from the editable IRCC originals."""
import os
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether

from .preparation import ordered_activities, is_confirmed, norm


def create_continuation(case, path, *, omit_absent=False):
    rows = ordered_activities(case)[3:]
    residences = [(i,r) for i,r in enumerate(case.residence_records) if is_confirmed(r)]
    # All confirmed residences are repeated here, including those whose country
    # or status could not be represented by an official dropdown option.
    travels = [(i,r) for i,r in enumerate(case.travel_records) if is_confirmed(r)]
    address_fallback = bool(case.contact.address.strip() and not case.official_review.residential_street_name.strip())
    if not rows and not residences and not travels and not address_fallback: return None
    fontfile = Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf'
    if 'CanadaVera' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('CanadaVera',str(fontfile)))
    body = ParagraphStyle('CanadaBody',fontName='CanadaVera',fontSize=9,leading=13,spaceAfter=6,wordWrap='CJK')
    heading = ParagraphStyle('CanadaHeading',parent=body,fontSize=13,leading=17,spaceBefore=12,spaceAfter=8,textColor=colors.HexColor('#18364c'),keepWithNext=True)
    story=[]
    used=[]
    def line(label,value):
        if omit_absent and not str(value).strip():
            return
        story.append(Paragraph(escape(label+': '+(str(value).strip() or '[REVIEW: not provided]')).replace('\n','<br/>'),body))
    story.append(Paragraph('IMM5257 - Supplementary information',heading))
    line('Applicant',case.display_name())
    line('Date of birth',case.identity.date_of_birth)
    line('Passport',case.passport.number)
    line('UCI',case.staff_review.uci if omit_absent else case.staff_review.uci or 'Not provided')
    story.append(Paragraph('DRAFT - Review with the accompanying official form. This attachment does not replace official validation or signatures.',body))
    if address_fallback:
        story.append(Paragraph('Residential address - complete source text',heading))
        line('Address',case.contact.address)
        line('City',case.contact.city)
        line('State / province',case.contact.state)
        line('Postal code',case.contact.postcode)
        line('Country (separate review)',case.contact.country)
        story.append(Paragraph('Complete intake address retained without splitting. Review the street, unit and number fields in the accompanying draft.',body))
        used.extend(['contact.address','contact.city','contact.state','contact.postcode'])
    if rows:
        story.append(Paragraph('Employment / activities - continuation after the three form rows',heading))
    for number,(i,a) in enumerate(rows,4):
        story.append(Paragraph(f'Activity {number}',heading))
        line('Period',a.start_date+' to '+('Present' if norm(a.ongoing_answer) in ('yes','sim') else a.end_date or '[end/status to confirm]'))
        line('Activity / occupation',a.position or a.activity_type)
        line('Employer / institution',a.organization)
        line('City',a.city)
        line('State / province',a.state)
        line('Country',a.country)
        if not a.ongoing_answer: line('Review','Ongoing/completed status is unconfirmed')
        for field in ('start_date','end_date','position','activity_type','organization','city','state','country','ongoing_answer'):
            if getattr(a,field): used.append(f'activities[{i}].{field}')
    for title,kind,records in (('Previous residence - confirmed records','residence',residences),
                               ('Travel history - confirmed supplementary records','travel',travels)):
        if records: story.append(Paragraph(title,heading))
        for i,r in records:
            first = len(story)
            line(f'Record {i+1}',r.country)
            line('Status / purpose',r.status_or_purpose)
            line('Period',r.start_date+' to '+r.end_date)
            story[first:] = [KeepTogether(story[first:])]
            story.append(Spacer(1,8))
            used.extend(f'{kind}_records[{i}].{field}' for field in ('country','status_or_purpose','start_date','end_date'))
    def footer(canvas,doc):
        if doc.page > 1:
            header=Paragraph(escape('Applicant: '+case.display_name()+' | Date of birth: '+(case.identity.date_of_birth or '[not provided]')),body)
            _,height=header.wrap(511,60)
            header.drawOn(canvas,42,822-height)
        canvas.setFont('CanadaVera',8)
        canvas.setFillColor(colors.HexColor('#52606b'))
        canvas.drawString(42,25,'IMM5257 supplementary information - DRAFT')
        canvas.drawRightString(553,25,f'Page {doc.page}')
    doc=SimpleDocTemplate(str(path),pagesize=(595,842),leftMargin=42,rightMargin=42,topMargin=72,bottomMargin=44,
                          title='IMM5257 supplementary information - DRAFT',author='Visa Automatic')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    os.chmod(path,0o600)
    return {'file':Path(path).name,'activity_count':len(rows),'residence_count':len(residences),
            'travel_count':len(travels),'sources':used}
