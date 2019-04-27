#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""server module."""
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import pprint
import sys
from tempfile import NamedTemporaryFile

from flask import (  # type: ignore
    __version__ as flask_version,
    abort,
    current_app,
    Flask,
    request,
    send_from_directory,
)
from flask.cli import FlaskGroup
from flask_admin import Admin
from flask_restful import Resource, Api
import click
import structlog
import requests

from iqdb_tagger.__main__ import (
    get_page_result,
    get_posted_image,
    init_program,
    iqdb_url_dict,
)
from iqdb_tagger.models import init_db
from iqdb_tagger.utils import default_db_path, thumb_folder, user_data_dir
from iqdb_tagger import views, models


__version__ = '0.2.1'
log = structlog.getLogger()


class MatchViewList(Resource):
    """Resource api for MatchViewList."""

    def post(self):  # pylint: disable=R0201
        """Post method for MatchViewList."""
        f = request.files['file']
        resize = True
        place = 'iqdb'
        with NamedTemporaryFile(delete=False) as temp, NamedTemporaryFile(delete=False) as thumb_temp:
            f.save(temp.name)
            posted_img = get_posted_image(
                img_path=temp.name, resize=resize, thumb_path=thumb_temp.name)
            url, im_place = iqdb_url_dict[place]
            query = posted_img.imagematchrelationship_set \
                .select().join(models.ImageMatch) \
                .where(models.ImageMatch.search_place == im_place)
            if not query.exists():
                try:
                    posted_img_path = temp.name if not resize else thumb_temp.name
                    result_page = get_page_result(image=posted_img_path, url=url)
                except requests.exceptions.ConnectionError as e:
                    current_app.logger.error(str(e))
                    abort(400, 'Connection error.')
                image_match = list(models.ImageMatch.get_or_create_from_page(  # NOQA
                    page=result_page, image=posted_img, place=im_place))
        raise NotImplementedError


def thumb(basename):
    """Get thumbnail."""
    return send_from_directory(thumb_folder, basename)


def create_app(script_info=None):
    """Create app."""
    app = Flask(__name__)
    # logging
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
    log_dir = os.path.join(user_data_dir, 'log')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    peewee_logger = logging.getLogger('peewee')
    peewee_logger.setLevel(logging.INFO)
    chardet_logger = logging.getLogger('chardet')
    chardet_logger.setLevel(logging.INFO)
    default_log_file = os.path.join(log_dir, 'iqdb_tagger_server.log')
    file_handler = TimedRotatingFileHandler(default_log_file, 'midnight')
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(logging.Formatter('<%(asctime)s> <%(levelname)s> %(message)s'))
    app.logger.addHandler(file_handler)
    app.logger.addHandler(peewee_logger)
    app.logger.addHandler(chardet_logger)
    # reloader
    reloader = app.config['TEMPLATES_AUTO_RELOAD'] = \
        bool(os.getenv('IQDB_TAGGER_RELOADER')) or app.config['TEMPLATES_AUTO_RELOAD']  # NOQA
    if reloader:
        app.jinja_env.auto_reload = True
    app.config['SECRET_KEY'] = os.getenv('IQDB_TAGGER_SECRET_KEY') or os.urandom(24)
    app.config['WTF_CSRF_ENABLED'] = False
    # debug
    debug = app.config['DEBUG'] = bool(os.getenv('IQDB_TAGGER_DEBUG')) or app.config['DEBUG']
    if debug:
        app.config['DEBUG'] = True
        app.config['LOGGER_HANDLER_POLICY'] = 'debug'
        logging.basicConfig(level=logging.DEBUG)
        pprint.pprint(app.config)
        print('Log file: {}'.format(default_log_file))
        print('script info:{}'.format(script_info))
    db_path = os.getenv('IQDB_TAGGER_DB_PATH') or default_db_path
    init_program()
    init_db(db_path)
    # app and db
    app.app_context().push()

    @app.shell_context_processor
    def shell_context():  # pylint: disable=unused-variable
        return {'app': app}

    # api
    api = Api(app)
    api.add_resource(MatchViewList, '/api/matchview')
    # flask-admin
    app_admin = Admin(
        app, name='IQDB Tagger', template_mode='bootstrap3',
        index_view=views.HomeView(name='Home', template='iqdb_tagger/index.html', url='/'))
    app_admin.add_view(views.MatchView())
    # app_admin.add_view(ModelView(ImageMatch, category='DB'))
    # app_admin.add_view(ModelView(ImageMatchRelationship, category='DB'))
    # app_admin.add_view(ModelView(ImageModel, category='DB'))
    # app_admin.add_view(ModelView(MatchTagRelationship, category='DB'))
    # routing
    app.add_url_rule('/thumb/<path:basename>', view_func=thumb)
    return app


class CustomFlaskGroup(FlaskGroup):
    """Custom Flask Group."""

    def __init__(self, **kwargs):
        """Class init."""
        super().__init__(**kwargs)
        self.params[0].help = 'Show the program version'
        self.params[0].callback = get_custom_version


def get_custom_version(ctx, _, value):
    """Get version."""
    if not value or ctx.resilient_parsing:
        return
    message = '%(app_name)s %(app_version)s\nFlask %(version)s\nPython %(python_version)s'
    click.echo(message % {
        'app_name': 'Iqdb-tagger',
        'app_version': __version__,
        'version': flask_version,
        'python_version': sys.version,
    }, color=ctx.color)
    ctx.exit()


@click.group(cls=CustomFlaskGroup, create_app=create_app)
def cli():
    """Run cli. This is a management script for application."""


if __name__ == '__main__':
    cli()
