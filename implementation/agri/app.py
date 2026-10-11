"""HTTP boundary for the agriculture ontology and traceability services."""
from __future__ import annotations
import json
import os
import secrets
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, jsonify, request, session, send_from_directory, send_file
from werkzeug.exceptions import HTTPException
from jsonschema import Draft202012Validator, FormatChecker

BASE = Path(__file__).resolve().parent.parent
MUTATIONS = {
    '/ontology/packages': 'register_package',
    '/ontology/entities': 'create_entity',
    '/ontology/type-assignments': 'assign_type',
    '/evidence': 'create_evidence',
    '/evidence/withdrawals': 'withdraw_evidence',
    '/observations': 'create_observation',
    '/assertions': 'create_assertion',
    '/assertions/reviews': 'review_assertion',
    '/ontology/relations': 'create_relation',
    '/trace/events': 'create_event',
    '/trace/lots': 'create_lot',
    '/trace/publications': 'publish',
    '/trace/recalls': 'recall',
    '/ontology/object-sets': 'create_object_set',
}
QUERIES = {
    '/ontology/packages': 'packages',
    '/ontology/entities': 'entities',
    '/ontology/relations': 'relations',
    '/ontology/graph': 'graph',
    '/trace/events': 'events',
    '/trace/lots': 'lots',
    '/evidence': 'evidence',
    '/observations': 'observations',
    '/assertions': 'assertions',
    '/trace/recalls': 'recalls',
    '/trace/publications': 'publications',
    '/trace/changes': 'changes',
    '/stats': 'stats',
    '/ontology/object-sets': 'object_sets',
    '/ontology/action-types': 'action_types',
}


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        TESTING=False,
        ALLOWED_HOSTS=['localhost', '127.0.0.1', '::1'],
        DATABASE_URL=os.getenv('DATABASE_URL', 'sqlite:///' + str(BASE / 'data' / 'agri.db')),
        DB_SCHEMA=os.getenv('DB_SCHEMA', 'agri'),
        PUBLIC_BASE_URL=os.getenv('AGRI_PUBLIC_BASE_URL', ''),
        AUTH_TOKENS={},
        DEMO_MODE=os.getenv('AGRI_DEMO_MODE', '1') == '1',
        SECRET_KEY=os.getenv('AGRI_SESSION_SECRET') or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_NAME='agri_session',
    )
    if config:
        app.config.update(config)
    tokens_path = BASE / 'data' / 'api-tokens.json'
    if not app.config['AUTH_TOKENS'] and tokens_path.exists():
        app.config['AUTH_TOKENS'] = json.loads(tokens_path.read_text(encoding='utf-8'))
    service = app.config.get('SERVICE')
    if service is None:
        from .db import Database
        from .service import Service
        database_url = app.config['DATABASE_URL']
        if database_url.startswith('sqlite:'):
            from .sqlite_db import SQLiteDatabase
            db = SQLiteDatabase(database_url)
        else:
            db = Database(database_url, app.config['DB_SCHEMA'])
        if app.config.get('AUTO_MIGRATE', True):
            db.migrate()
        service = Service(db)
        app.extensions['agri_db'] = db
    app.extensions['agri_service'] = service
    schema_path = BASE / 'contracts' / 'input-schemas.json'
    schema_map = json.loads(schema_path.read_text(encoding='utf-8')) if schema_path.exists() else {}
    validators = {name: Draft202012Validator(s, format_checker=FormatChecker()) for name, s in schema_map.items()}

    def fail(status, code, message, details=None):
        body = {'error': {'code': code, 'message': message, 'request_id': getattr(request, 'request_id', None)}}
        if details is not None:
            body['error']['details'] = details
        return jsonify(body), status

    @app.before_request
    def assign_request_id():
        request.request_id = str(uuid.uuid4())
        host = urlsplit('http://' + request.host).hostname
        if host not in app.config['ALLOWED_HOSTS']:
            return fail(403, 'host_denied', '当前服务仅接受配置的主机名')
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('Origin')
            if origin and (urlsplit(origin).netloc != request.host or urlsplit(origin).scheme != request.scheme):
                return fail(403, 'origin_denied', '跨来源写入已拒绝')

    @app.after_request
    def response_headers(response):
        response.headers['X-Request-ID'] = request.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    def authenticate():
        header = request.headers.get('Authorization', '')
        if header:
            if not header.startswith('Bearer '):
                return None
            value = header[7:]
            actor = app.config['AUTH_TOKENS'].get(value)
            return dict(actor) if actor else None
        actor_id = session.get('demo_actor')
        if app.config['DEMO_MODE'] and actor_id:
            if request.remote_addr not in ('127.0.0.1', '::1'):
                return None
            role = session.get('demo_role')
            if role not in ('admin', 'reviewer', 'operator', 'viewer'):
                return None
            return {'id': actor_id, 'tenant_id': 'demo-farm', 'roles': [role]}
        return None

    def protected(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            actor = authenticate()
            if not actor or not actor.get('id') or not actor.get('tenant_id'):
                return fail(401, 'authentication_required', '需要有效的访问身份')
            request.actor = actor
            request.tenant = actor['tenant_id']
            return fn(*args, **kwargs)
        return call

    def payload():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError('请求体必须为 JSON 对象')
        return body

    @app.errorhandler(Exception)
    def errors(exc):
        from .service import DomainError
        if isinstance(exc, DomainError):
            return fail(exc.status, exc.code, exc.message, exc.details)
        if isinstance(exc, HTTPException):
            return fail(exc.code, 'http_error', exc.description)
        if isinstance(exc, (ValueError, TypeError, KeyError)):
            return fail(422, 'invalid_request', str(exc))
        app.logger.exception('Unhandled request error %s', request.request_id)
        return fail(500, 'internal_error', '服务异常，请按 request_id 查阅日志')

    def mutation(action):
        @protected
        def handler():
            key = request.headers.get('Idempotency-Key', '')
            if not key or len(key) > 200:
                return fail(422, 'idempotency_key_required', '写入需要长度不超过 200 的 Idempotency-Key')
            body = payload()
            if action in validators:
                issues = list(validators[action].iter_errors(body))
                if issues:
                    return fail(422, 'schema_validation_failed', '输入不符合数据契约', [{'path': list(e.path), 'message': e.message} for e in issues[:10]])
            result = service.mutate(action, request.tenant, request.actor, body, key)
            return jsonify({'data': result, 'request_id': request.request_id}), 200
        return handler

    def query(action):
        @protected
        def handler(**path_params):
            params = request.args.to_dict()
            params.update(path_params)
            if action == 'graph' and hasattr(service, 'db'):
                from .network import build_network
                result = build_network(service, request.tenant, request.actor, params)
            else:
                result = service.query(action, request.tenant, request.actor, params)
            return jsonify({'data': result, 'request_id': request.request_id})
        return handler

    for path, action in MUTATIONS.items():
        app.add_url_rule('/api/v1' + path, 'mutate_' + action, mutation(action), methods=['POST'])
    for path, action in QUERIES.items():
        app.add_url_rule('/api/v1' + path, 'query_' + action, query(action), methods=['GET'])
    app.add_url_rule('/api/v1/ontology/entities/<entity_key>', 'entity', query('entity'))
    app.add_url_rule('/api/v1/trace/lots/<lot_key>/lineage', 'lineage', query('lineage'))
    app.add_url_rule('/api/v1/trace/lots/<lot_key>/bundle', 'trace_bundle', query('trace_bundle'))
    app.add_url_rule('/api/v1/inference/bundles/<entity_key>', 'evidence_bundle', query('evidence_bundle'))

    app.add_url_rule('/api/v1/evidence/<evidence_id>', 'evidence_item', query('evidence'))
    app.add_url_rule('/api/v1/trace/events/<event_id>', 'event_item', query('events'))

    @app.get('/api/v1/evidence/<evidence_id>/asset')
    @protected
    def evidence_asset(evidence_id):
        import hashlib
        import re
        item = service.query('evidence', request.tenant, request.actor, {'evidence_id': evidence_id})
        meta = item.get('metadata', {})
        digest = meta.get('asset_key', '')
        if not re.fullmatch('[0-9a-f]{64}', digest):
            return fail(404, 'asset_unavailable', '该证据没有本地原始资产')
        path = BASE / 'data' / 'assets' / hashlib.sha256(request.tenant.encode()).hexdigest() / digest
        if not path.is_file():
            return fail(404, 'asset_unavailable', '原始资产不可用')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['content_hash']:
            return fail(409, 'asset_integrity_failed', '原始资产完整性检查失败')
        return send_file(path, mimetype='application/octet-stream', as_attachment=True,
                         download_name=Path(meta.get('filename', 'evidence.bin')).name)

    @app.get('/api/v1/ontology/export')
    @protected
    def graph_export():
        from .network import build_network
        from .exchange import to_jsonld, to_turtle
        params = request.args.to_dict()
        fmt = params.pop('format', 'jsonld')
        if fmt not in ('jsonld', 'turtle'):
            return fail(422, 'unsupported_format', '支持 jsonld 或 turtle')
        graph = build_network(service, request.tenant, request.actor, params)
        if fmt == 'turtle':
            return app.response_class(to_turtle(graph), mimetype='text/turtle')
        return app.response_class(json.dumps(to_jsonld(graph), ensure_ascii=False), mimetype='application/ld+json')

    @app.get('/api/v1/health')
    def health():
        return jsonify({'status': 'ok', 'application': 'liangzihu-ontology', 'version': '0.1.0',
                        'mode': 'local-engineering', 'demo_mode': app.config['DEMO_MODE'],
                        'backend': 'sqlite' if app.config['DATABASE_URL'].startswith('sqlite:') else 'postgresql'})

    @app.get('/api/v1/auth/me')
    @protected
    def me():
        return jsonify({'data': request.actor})

    @app.post('/api/v1/auth/demo')
    def demo_login():
        if not app.config['DEMO_MODE'] or request.remote_addr not in ('127.0.0.1', '::1'):
            return fail(404, 'not_found', '接口不存在')
        role = payload().get('role', 'viewer')
        if role not in ('admin', 'operator', 'reviewer', 'viewer'):
            return fail(422, 'invalid_role', '无效演示角色')
        session.clear()
        session['demo_actor'] = 'demo-' + role
        session['demo_role'] = role
        return jsonify({'data': {'id': 'demo-' + role, 'tenant_id': 'demo-farm', 'roles': [role], 'synthetic': True}})

    @app.post('/api/v1/auth/logout')
    def logout():
        session.clear()
        return jsonify({'data': {'logged_out': True}})

    @app.get('/api/v1/public/trace/<code>')
    def public_trace(code):
        if len(code) > 200:
            return fail(404, 'not_found', '公开码不存在')
        return jsonify({'data': service.public_trace(code), 'request_id': request.request_id})

    @app.get('/api/v1/public/trace/<code>/qr.svg')
    def public_qr(code):
        service.public_trace(code)
        from .qr import make_svg
        base_url = app.config['PUBLIC_BASE_URL'].rstrip('/') or request.url_root.rstrip('/')
        if urlsplit(base_url).scheme not in ('http', 'https'):
            return fail(500, 'invalid_public_url', '公开访问地址未正确配置')
        return app.response_class(make_svg(base_url + '/trace/' + code), mimetype='image/svg+xml')

    @app.get('/api/v1/openapi.json')
    def openapi():
        return jsonify(build_openapi())

    @app.get('/')
    @app.get('/trace/<code>')
    def home(code=None):
        return send_from_directory(BASE / 'web', 'index.html')

    @app.get('/assets/<path:name>')
    def assets(name):
        return send_from_directory(BASE / 'web', name)

    from .ingestion import create_ingestion_blueprint
    app.register_blueprint(create_ingestion_blueprint(service, authenticate, BASE))
    return app


def build_openapi():
    from .openapi import describe
    return describe(BASE, MUTATIONS, QUERIES)
