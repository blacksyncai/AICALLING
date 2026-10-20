"""Provider exports use the existing contact importer, never paid address lookup."""
import pytest
from app.services.contacts import parse_contacts_csv

@pytest.mark.parametrize('phone_column', ['Phone 1', 'Phone1', 'Primary Phone'])
def test_owner_export_headers(phone_column):
    rows, skipped = parse_contacts_csv(f'Owner First Name,Owner Last Name,{phone_column},Address,City\nAli,Hassan,4155550187,"123 Main St, Apt 2",Oakland\nNo,Phone,,456 Main St,Oakland')
    assert skipped == 1
    assert rows[0]['name'] == 'Ali Hassan'
    assert rows[0]['phone'] == '+14155550187'
    assert rows[0]['custom_fields']['address'] == '123 Main St, Apt 2'
    assert rows[0]['custom_fields']['owner_first_name'] == 'Ali'


def test_provider_import_is_tagged_and_deduplicated(client):
    body = {'csv': 'Owner First Name,Owner Last Name,Phone 1,City\nProvider,Import,4155550196,Oakland',
            'tags': ['source:vulcan7']}
    first = client.post('/api/contacts/import', json=body)
    assert first.status_code == 201
    assert first.json()['created'] == 1
    again = client.post('/api/contacts/import', json=body)
    assert again.status_code == 201 and again.json()['duplicates'] == 1
    contacts = client.get('/api/contacts', params={'q': 'Provider Import'}).json()
    row = next(c for c in contacts['items'] if c['phone'] == '+14155550196')
    assert 'source:vulcan7' in row['tags']
    assert row['campaign_id'] is None
