import pytest

from src.privacy import PrivacyError, get_salt, hash_customer

SALT = 'unit-test-salt-0123456789'


def test_same_customer_gets_same_id():
    assert hash_customer('Jane D.', 'Clayton', SALT) == hash_customer(
        'Jane D.', 'Clayton', SALT
    )


def test_hash_ignores_case_and_extra_whitespace():
    assert hash_customer('Jane D.', 'Clayton', SALT) == hash_customer(
        '  jane   d. ', 'CLAYTON', SALT
    )


def test_different_suburb_gives_different_id():
    assert hash_customer('Jane D.', 'Clayton', SALT) != hash_customer(
        'Jane D.', 'Dandenong', SALT
    )


def test_different_salt_gives_different_id():
    other = 'another-salt-0123456789'
    assert hash_customer('Jane D.', 'Clayton', SALT) != hash_customer(
        'Jane D.', 'Clayton', other
    )


def test_hash_does_not_contain_the_name():
    result = hash_customer('Jane D.', 'Clayton', SALT)
    assert 'jane' not in result.lower()
    assert 'clayton' not in result.lower()


@pytest.mark.parametrize('name', [None, '', '   '])
def test_blank_customer_has_no_id(name):
    assert hash_customer(name, 'Clayton', SALT) is None


def test_missing_suburb_still_hashes():
    assert hash_customer('Jane D.', None, SALT) is not None


def test_short_salt_is_rejected():
    with pytest.raises(PrivacyError):
        hash_customer('Jane D.', 'Clayton', 'short')


def test_get_salt_fails_closed_when_unset(monkeypatch):
    monkeypatch.delenv('CUSTOMER_HASH_SALT', raising=False)
    with pytest.raises(PrivacyError):
        get_salt()


def test_get_salt_reads_environment(monkeypatch):
    monkeypatch.setenv('CUSTOMER_HASH_SALT', SALT)
    assert get_salt() == SALT
