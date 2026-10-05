"""Explicit draft-header support, plus verified legacy narrative fields.

These aliases are a proposal. The actual 234-column revised export is handled
separately by verified_intake.py after its complete header fingerprint matches. Repeated
legacy contact/activity headers continue to use the existing section reader.
"""
from .models import Activity, FamilyMember


FIELDS = {
    'identity.family_name': ('Sobrenome conforme passaporte',),
    'identity.given_names': ('Todos os nomes conforme passaporte',),
    'identity.full_name': ('Nome completo conforme passaporte',),
    'identity.sex': ('Sexo',),
    'identity.birth_country': ('País de nascimento',),
    'identity.nationality': ('Nacionalidade atual',),
    'identity.residence_country': ('País de residência atual',),
    'identity.residence_status': ('Status migratório no país de residência atual',),
    'identity.residence_since': ('Desde quando reside no país atual?',),
    'contact.address': ('Endereço residencial completo',),
    'contact.postcode': ('CEP residencial',),
    'contact.city': ('Cidade residencial',),
    'contact.state': ('Estado residencial',),
    'contact.email': ('E-mail do requerente',),
    'contact.phone': ('Telefone do requerente',),
    'trip.available_funds_cad': ('Fundos disponíveis para a viagem em CAD',),
    'trip.payer': ('Quem pagará a viagem?',),
    'trip.visiting_person_or_institution': ('Você vai visitar uma pessoa ou instituição no Canadá?',),
    'trip.host_name': ('Nome completo da pessoa ou instituição no Canadá',),
    'trip.relationship': ('Relação com o requerente',),
    'trip.host_address': ('Endereço completo do anfitrião no Canadá',),
    'trip.host_postcode': ('CEP/código postal do anfitrião no Canadá',),
    'trip.host_phone': ('Telefone do anfitrião no Canadá',),
    'trip.host_email': ('E-mail do anfitrião no Canadá',),
    'relationships.spouse_given_names': ('Nomes do cônjuge',),
    'relationships.spouse_birth_country': ('País de nascimento do cônjuge',),
    'relationships.spouse_residence_answer': ('O cônjuge mora com você?',),
    'relationships.spouse_address': ('Endereço do cônjuge, se diferente',),
    'relationships.spouse_accompanying_answer': ('O cônjuge viajará com você ao Canadá?',),
    'relationships.former_spouse_family_name': ('Sobrenome do ex-cônjuge',),
    'relationships.former_spouse_given_names': ('Nomes do ex-cônjuge',),
    'relationships.former_spouse_birth_country': ('País de nascimento do ex-cônjuge',),
    'relationships.former_spouse_residence_answer': ('O ex-cônjuge mora com você?',),
    'relationships.former_spouse_address': ('Endereço do ex-cônjuge, se diferente',),
    'relationships.former_spouse_accompanying_answer': ('O ex-cônjuge viajará com você ao Canadá?',),
    'relationships.has_previous_relationship': ('Já foi casado(a) ou teve união estável anteriormente?',),
    'family.has_children_answer': ('Possui filhos?',),
    'history.previous_residences': ('Se sim, informe: país + status migratório nesse país + data de início da residência + data de término da residência',),
    'history.travelled_abroad_answer': ('Nos últimos 10 anos, você viajou para outros países?',),
    'history.travel_details': ('Informe os países visitados, data de entrada, data de saída e motivo da viagem', 'Histórico de viagens — países, datas e motivo'),
    'history.previous_canada_visa_answer': ('Já teve visto canadense anteriormente?',),
    'history.canada_refusal_answer': ('Já teve pedido de visto, entrada ou permanência no Canadá recusado?',),
    'history.other_refusal_answer': ('Já teve visto ou entrada recusada por outro país?',),
    'history.previously_in_canada_answer': ('Já esteve no Canadá anteriormente?',),
    'history.immigration_details': ('Detalhes de respostas Sim sobre imigração',),
    'history.criminal_history_answer': ('Já cometeu, foi preso, acusado ou condenado por algum crime?',),
    'history.service_history_answer': ('Já trabalhou ou se envolveu com forças militares, policiais, segurança, inteligência ou grupos armados?',),
    'history.immigration_problems_answer': ('Já teve algum problema relacionado à imigração ou permanência em outro país?',),
    'history.overstay_answer': ('Já permaneceu em algum país após o vencimento de seu visto, incluindo o Canadá?',),
    'history.declaration_details': ('Se respondeu "Sim" a alguma declaração, forneça todos os detalhes relevantes, incluindo datas, país, circunstâncias, resultado e documentação disponível', 'Detalhes de respostas Sim sobre declarações'),
    'letters.introduction': ('Quem é você? (nome completo, idade e breve apresentação pessoal)', 'Carta de intenção — apresentação pessoal'),
    'letters.reason_for_canada': ('Por que você escolheu ir especificamente para o Canadá, e não para outro país?', 'Carta de intenção — motivo para escolher o Canadá'),
    'letters.planned_activities': ('O que pretende fazer durante sua estadia no Canadá? (turismo, estudo, visita familiar, negócios etc.)', 'Carta de intenção — atividades planejadas no Canadá'),
    'letters.return_plans': ('Quais são seus planos após o término da viagem e retorno ao Brasil?', 'Carta de intenção — plano após retorno ao Brasil'),
}

PARENT_FIELDS = {
    'family_name': 'Sobrenome {person}',
    'given_names': 'Nomes {person}',
    'full_name': 'Nome completo {person}',
    'birth_country': 'País de nascimento {person}',
    'date_of_birth': 'Data de nascimento {person}',
    'birth_place': 'Cidade de nascimento {person}',
    'marital_status': 'Estado civil {person}',
    'occupation': 'Ocupação atual {person}',
    'address': 'Endereço completo {person}',
    'death_details': 'Dados de falecimento {person}',
    'accompanying_answer': '{subject} viajará com você ao Canadá?',
}
CHILD_FIELDS = {
    'family_name': 'Sobrenome do filho {n}',
    'given_names': 'Nomes do filho {n}',
    'date_of_birth': 'Data de nascimento do filho {n}',
    'birth_country': 'País de nascimento do filho {n}',
    'relationship': 'Relação do filho {n} com o requerente',
    'marital_status': 'Estado civil do filho {n}',
    'occupation': 'Ocupação atual do filho {n}',
    'address': 'Endereço completo do filho {n}',
    'accompanying_answer': 'O filho {n} viajará com você ao Canadá?',
    'has_more_children_answer': 'Possui outro filho além do filho {n}?',
}
ACTIVITY_FIELDS = {
    'activity_type': 'tipo', 'start_date': 'início', 'end_date': 'término',
    'ongoing_answer': 'em andamento?', 'position': 'cargo',
    'organization': 'organização', 'city': 'cidade', 'state': 'estado/província',
}


def apply_updated_intake(case, row):
    from .source_readers import _column_indexes, _column_value

    def read(labels):
        indexes = _column_indexes(row, *labels)
        if len(indexes) > 1:
            raise ValueError('Ambiguous Canada field; review duplicate or mixed headers: ' + labels[0])
        return _column_value(row, indexes[0]) if indexes else None

    for path, labels in FIELDS.items():
        value = read(labels)
        if value is not None:
            group, field = path.split('.')
            setattr(getattr(case, group), field, value)

    updated = any(read(labels) is not None for path, labels in FIELDS.items()
                  if not path.startswith(('history.', 'letters.')))
    # New components do not establish which historical slot is mother or father.
    for parent in case.family.parents:
        number = parent.source_block_index
        for field, labels in {
            'family_name': (f'Sobrenome do genitor {number}',),
            'given_names': (f'Nomes do genitor {number}', f'Nome do genitor {number}'),
            'birth_country': (f'País de nascimento do genitor {number}',),
        }.items():
            value = read(labels)
            if value is not None:
                setattr(parent, field, value)
                updated = True
    parents = []
    for block, person, subject, role in ((1, 'da mãe', 'A mãe', 'mother'), (2, 'do pai', 'O pai', 'father')):
        values = {field: read((title.format(person=person, subject=subject),))
                  for field, title in PARENT_FIELDS.items()}
        # An explicit mother/father header is sufficient; source order is irrelevant.
        if any(value is not None for value in values.values()):
            parents.append(FamilyMember(source_block_index=block, source_role=role,
                                        confirmed_role=role,
                                        **{field: value or '' for field, value in values.items()}))
    if parents:
        if case.family.parents:
            raise ValueError('Mixed generic parent and explicit mother/father sections; reconcile before importing')
        case.family.parents = parents
        updated = True

    children, activities = [], []
    for i in range(1, 6):
        values = {field: read((title.format(n=f'{i:02}'),)) for field, title in CHILD_FIELDS.items()}
        if any(value is not None for value in values.values()):
            children.append(FamilyMember(source_block_index=i, source_role='child',
                                         **{field: value or '' for field, value in values.items()}))
        values = {field: read((f'Atividade {i:02} — {suffix}',)) for field, suffix in ACTIVITY_FIELDS.items()}
        if any(value is not None for value in values.values()):
            activities.append(Activity(source_block_index=i, source_role='csv',
                                       **{field: value or '' for field, value in values.items()}))
    if children:
        if case.family.children:
            raise ValueError('Mixed numbered and legacy child sections; reconcile before importing')
        case.family.children = children
        updated = True
    if activities:
        if case.activities:
            raise ValueError('Mixed numbered and legacy activity sections; reconcile before importing')
        case.activities = activities
        updated = True
    if updated:
        case.import_profile = 'updated_unverified'
    case.source_email = case.contact.email
    return case
