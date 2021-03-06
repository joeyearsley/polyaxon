import json

import django_auth_ldap.config as django_auth_ldap_config
import ldap

from polyaxon.config_manager import config

DEFAULT_EMAIL_DOMAIN = 'local_polyaxon.com'

AUTH_LDAP_ENABLED = config.get_boolean('POLYAXON_AUTH_LDAP', is_optional=True, is_local=True)

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

ACCESS_BACKEND = config.get_string('POLYAXON_ACCESS_BACKEND', is_optional=True)

if AUTH_LDAP_ENABLED:
    AUTHENTICATION_BACKENDS = ['django_auth_ldap.backend.LDAPBackend'] + AUTHENTICATION_BACKENDS

    AUTH_LDAP_SERVER_URI = config.get_string('POLYAXON_AUTH_LDAP_SERVER_URI')

    # set ldap global options
    ldap_global_options = config.get_string('POLYAXON_AUTH_LDAP_GLOBAL_OPTIONS', is_optional=True)
    if ldap_global_options:
        ldap_global_options = json.loads(ldap_global_options)
        for option_name in ldap_global_options:
            option = getattr(ldap, option_name)
            ldap.set_option(option, ldap_global_options[option_name])

    # set ldap connection options
    AUTH_LDAP_CONNECTION_OPTIONS = {}
    ldap_conn_options = config.get_string('POLYAXON_AUTH_LDAP_CONNECTION_OPTIONS', is_optional=True)
    if ldap_conn_options:
        ldap_conn_options = json.loads(ldap_conn_options)
        for option_name in ldap_conn_options:
            option = getattr(ldap, option_name)
            AUTH_LDAP_CONNECTION_OPTIONS[option] = ldap_conn_options[option_name]

    AUTH_LDAP_BIND_DN = config.get_string('POLYAXON_AUTH_LDAP_BIND_DN', is_optional=True)
    AUTH_LDAP_BIND_PASSWORD = config.get_string('POLYAXON_AUTH_LDAP_BIND_PASSWORD',
                                                is_secret=True,
                                                is_optional=True)
    base_dn = config.get_string('POLYAXON_AUTH_LDAP_USER_SEARCH_BASE_DN', is_optional=True)
    filterstr = config.get_string('POLYAXON_AUTH_LDAP_USER_SEARCH_FILTERSTR', is_optional=True)
    if base_dn and filterstr:
        AUTH_LDAP_USER_SEARCH = django_auth_ldap_config.LDAPSearch(
            base_dn,
            ldap.SCOPE_SUBTREE,
            filterstr
        )

    AUTH_LDAP_USER_DN_TEMPLATE = config.get_string('POLYAXON_AUTH_LDAP_USER_DN_TEMPLATE',
                                                   is_optional=True)
    # when USER_DN_TEMPLATE is empty string, all users will login as anonymous user.
    if AUTH_LDAP_USER_DN_TEMPLATE == '':
        AUTH_LDAP_USER_DN_TEMPLATE = None

    AUTH_LDAP_START_TLS = config.get_boolean('POLYAXON_AUTH_LDAP_START_TLS', is_optional=True)

    user_attr_map = config.get_string('POLYAXON_AUTH_LDAP_USER_ATTR_MAP', is_optional=True)
    if user_attr_map:
        AUTH_LDAP_USER_ATTR_MAP = json.loads(user_attr_map)

    # working with groups
    group_base_dn = config.get_string('POLYAXON_AUTH_LDAP_GROUP_SEARCH_BASE_DN', is_optional=True)
    group_type = config.get_string('POLYAXON_AUTH_LDAP_GROUP_SEARCH_GROUP_TYPE', is_optional=True)
    if group_base_dn and group_type:
        AUTH_LDAP_GROUP_SEARCH = django_auth_ldap_config.LDAPSearch(
            group_base_dn,
            ldap.SCOPE_SUBTREE,
            "(objectClass=%s)" % group_type
        )
        AUTH_LDAP_GROUP_TYPE = getattr(django_auth_ldap_config,
                                       group_type[0].upper() + group_type[1:] + 'Type')()

    AUTH_LDAP_REQUIRE_GROUP = config.get_string('POLYAXON_AUTH_LDAP_REQUIRE_GROUP',
                                                is_optional=True)
    AUTH_LDAP_DENY_GROUP = config.get_string('POLYAXON_AUTH_LDAP_DENY_GROUP', is_optional=True)
