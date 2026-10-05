"""Small explicit label dictionary. Unknown words remain subject to review."""
from .preparation import norm

LABELS = {
 'CountryOfBirthList': {'brasil':'Brazil','portugal':'Portugal','canada':'Canada','estados unidos':'United States of America'},
 'CountryOfCitizenshipList': {'brasil':'Brazil','brasileira':'Brazil','brasileiro':'Brazil','portuguesa':'Portugal','portugues':'Portugal'},
 'CountryOfLastPermanentResidentList': {'brasil':'Brazil','canada':'Canada','portugal':'Portugal'},
 'CountryTravelDocumentList': {'brasil':'Brazil','canada':'Canada','portugal':'Portugal'},
 'GenderMelList': {'masculino':'Male','feminino':'Female'},
 'PreferenceLanguageList': {'ingles':'English','frances':'French'},
 'ContactLanguageList': {'portugues':'Portuguese','ingles':'English','frances':'French'},
 'MaritalStatusList': {'solteiro':'Single','solteira':'Single','casado':'Married','casada':'Married',
     'divorciado':'Divorced','divorciada':'Divorced','viuvo':'Widowed','viuva':'Widowed',
     'uniao estavel':'Common-law','separado legalmente':'Legally Separated','separada legalmente':'Legally Separated'},
 'MaritalStatusHistoryList': {'casamento':'Married','uniao estavel':'Common-law'},
 'ImmigrationStatusList': {'cidadao':'Citizen','cidada':'Citizen','residente permanente':'Permanent resident',
     'visitante':'Visitor','estudante':'Student','trabalhador':'Worker','trabalhadora':'Worker'},
 'VisitPurposeList': {'turismo':'Tourism','visita familiar':'Family Visit','negocios':'Business'},
}


def translate(value, list_name):
    return LABELS.get(list_name,{}).get(norm(value),value)
