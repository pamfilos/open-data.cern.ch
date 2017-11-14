# -*- coding: utf-8 -*-
#
# This file is part of CERN Open Data Portal.
# Copyright (C) 2017 CERN.
#
# CERN Open Data Portal is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# CERN Open Data Portal is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

"""Command line interface for CERN Open Data Portal."""

from __future__ import absolute_import, print_function

import glob
import json
import os
import uuid

import click
import pkg_resources
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy.orm.attributes import flag_modified


def get_jsons_from_dir(dir):
    """Get JSON files inside a dir."""
    res = []
    for root, dirs, files in os.walk(dir):
        for file in files:
            if file.endswith(".json"):
                res.append(os.path.join(root, file))
    return res


@click.group(chain=True)
def fixtures():
    """Automate site bootstrap process and testing."""


@fixtures.command()
@click.option('--skip-files', is_flag=True, default=False,
              help='Skip loading of files')
@click.option('files', '--file', '-f', multiple=True,
              type=click.Path(exists=True),
              help='Path to the file(s) to be loaded. If not provided, all'
                   'files will be loaded')
@click.option('--profile', is_flag=True,
              help='Output profiling information.')
@click.option('--verbose', is_flag=True, default=False)
@with_appcontext
def records(skip_files, files, profile, verbose):
    """Load all records."""
    if profile:
        import cProfile
        import pstats
        import StringIO
        pr = cProfile.Profile()
        pr.enable()

    from invenio_db import db
    # from invenio_records_files.api import Record
    from cernopendata.modules.records.api import Record
    from invenio_indexer.api import RecordIndexer
    from cernopendata.modules.records.minters.recid import \
        cernopendata_recid_minter

    from invenio_files_rest.models import \
        Bucket, FileInstance, ObjectVersion
    from invenio_records_files.models import RecordsBuckets

    indexer = RecordIndexer()
    schema = current_app.extensions['invenio-jsonschemas'].path_to_url(
        'records/record-v1.0.0.json'
    )
    data = pkg_resources.resource_filename('cernopendata',
                                           'modules/fixtures/data/records')
    if files:
        record_json = files
    else:
        record_json = glob.glob(os.path.join(data, '*.json'))

    for filename in record_json:
        with open(filename, 'rb') as source:
            for data in json.load(source):

                if not data:
                    continue

                if verbose:
                    click.echo('Loading {0} ...'.format(filename))

                files = data.pop('files', [])

                id = uuid.uuid4()
                cernopendata_recid_minter(id, data)
                record = Record.create(data, id_=id)
                record['$schema'] = schema
                bucket = Bucket.create()
                RecordsBuckets.create(
                    record=record.model, bucket=bucket)

                record_files = record.files

                for file in files[1:]:
                    if skip_files:
                        break
                    assert 'uri' in file
                    assert 'size' in file
                    assert 'checksum' in file

                    try:
                        filename = file.get("uri").split('/')[-1:][0]

                        record_files[filename] = {
                            "uri": file.get("uri"),
                            "size": file.get("size"),
                            "checksum": file.get("checksum"),
                            "data": {
                                "filetype": file.get("type", "fileee")
                            }
                        }
                    except Exception as e:
                        click.echo(
                            'Recid {0} file {1} could not be loaded due '
                            'to {2}.'.format(data.get('recid'), filename,
                                             str(e)))
                        continue

                record_files.flush()
                record.commit()

                db.session.commit()
                indexer.index(record)
                db.session.expunge_all()

    if profile:
        pr.disable()
        s = StringIO.StringIO()
        sortby = 'cumulative'
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats()
        print(s.getvalue())


@fixtures.command()
@with_appcontext
def glossary_terms():
    """Load demo terms records."""
    from invenio_db import db
    from invenio_records import Record
    from invenio_indexer.api import RecordIndexer
    from cernopendata.modules.records.minters.termid import \
        cernopendata_termid_minter

    indexer = RecordIndexer()
    schema = current_app.extensions['invenio-jsonschemas'].path_to_url(
        'records/glossary-term-v1.0.0.json'
    )
    data = pkg_resources.resource_filename('cernopendata',
                                           'modules/fixtures/data')
    glossary_terms_json = glob.glob(os.path.join(data, 'terms', '*.json'))

    for filename in glossary_terms_json:
        with open(filename, 'rb') as source:
            for data in json.load(source):
                if "collections" not in data and \
                   not isinstance(data.get("collections", None), basestring):
                    data["collections"] = []
                data["collections"].append({"primary": "Terms"})
                id = uuid.uuid4()
                cernopendata_termid_minter(id, data)
                record = Record.create(data, id_=id)
                record['$schema'] = schema
                db.session.commit()
                indexer.index(record)
                db.session.expunge_all()


@fixtures.command()
@with_appcontext
def articles():
    """Load demo article records."""
    from invenio_db import db
    from invenio_records import Record
    from invenio_indexer.api import RecordIndexer
    from cernopendata.modules.records.minters.artid import \
        cernopendata_articleid_minter

    indexer = RecordIndexer()
    schema = current_app.extensions['invenio-jsonschemas'].path_to_url(
        'records/article-v1.0.0.json'
    )
    data = pkg_resources.resource_filename('cernopendata',
                                           'modules/fixtures/data/articles')

    articles_json = get_jsons_from_dir(data)

    for filename in articles_json:
        with open(filename, 'rb') as source:
            for data in json.load(source):

                # Replace body with responding content
                assert data["body"]["content"]
                content_filename = os.path.join(
                    *(
                        ["/", ] +
                        filename.split('/')[:-1] +
                        [data["body"]["content"], ]
                    )
                )

                with open(content_filename) as body_field:
                    data["body"]["content"] = body_field.read()
                if "collections" not in data and \
                   not isinstance(data.get("collections", None), basestring):
                    data["collections"] = []
                id = uuid.uuid4()
                cernopendata_articleid_minter(id, data)
                record = Record.create(data, id_=id)
                record['$schema'] = schema
                db.session.commit()
                indexer.index(record)
                db.session.expunge_all()


@fixtures.command()
@click.option('--skip-files', is_flag=True, default=False,
              help='Skip loading of files')
@with_appcontext
def data_policies(skip_files):
    """Load demo Data Policy records."""
    from invenio_db import db
    from invenio_indexer.api import RecordIndexer
    from cernopendata.modules.records.minters.recid import \
        cernopendata_recid_minter

    from invenio_files_rest.models import \
        Bucket, FileInstance, ObjectVersion
    from invenio_records_files.models import RecordsBuckets
    from invenio_records_files.api import Record
    from invenio_records.models import RecordMetadata

    indexer = RecordIndexer()
    schema = current_app.extensions['invenio-jsonschemas'].path_to_url(
        'records/data-policies-v1.0.0.json'
    )
    data = pkg_resources.resource_filename('cernopendata',
                                           'modules/fixtures/data')
    data_policies_json = glob.glob(os.path.join(data, '*.json'))

    for filename in data_policies_json:
        with open(filename, 'rb') as source:
            for data in json.load(source):
                files = data.pop('files', [])

                id = uuid.uuid4()
                cernopendata_recid_minter(id, data)
                record = Record.create(data, id_=id)
                record['$schema'] = schema
                bucket = Bucket.create()
                RecordsBuckets.create(
                    record=record.model, bucket=bucket)

                for file in files:
                    if skip_files:
                        break
                    assert 'uri' in file
                    assert 'size' in file
                    assert 'checksum' in file

                    f = FileInstance.create()
                    filename = file.get("uri").split('/')[-1:][0]
                    f.set_uri(file.get("uri"), file.get(
                        "size"), file.get("checksum"))
                    ObjectVersion.create(
                        bucket,
                        filename,
                        _file_id=f.id
                    )
                db.session.commit()
                indexer.index(record)
                db.session.expunge_all()


@fixtures.command()
@click.option('--skip-files', is_flag=True, default=False,
              help='Skip loading of files')
@with_appcontext
def datasets(skip_files):
    """Load demo datasets records."""
    from invenio_db import db
    from invenio_records_files.api import Record
    from invenio_indexer.api import RecordIndexer
    from cernopendata.modules.records.minters.recid import \
        cernopendata_recid_minter
    from cernopendata.modules.records.minters.datasetid import \
        cernopendata_datasetid_minter

    from invenio_files_rest.models import \
        Bucket, FileInstance, ObjectVersion
    from invenio_records_files.models import RecordsBuckets

    indexer = RecordIndexer()
    schema = current_app.extensions['invenio-jsonschemas'].path_to_url(
        'records/datasets-v1.0.0.json'
    )
    data = pkg_resources.resource_filename('cernopendata',
                                           'modules/fixtures/data/datasets')
    datasets_json = glob.glob(os.path.join(data, '*.json'))

    for filename in datasets_json:
        with open(filename, 'rb') as source:
            for data in json.load(source):
                files = data.pop('files', [])

                id = uuid.uuid4()
                # (TOFIX) Remove if statement in production
                # as every dataset record should have a doi
                if data.get('doi', None):
                    cernopendata_datasetid_minter(id, data)
                else:
                    cernopendata_recid_minter(id, data)
                record = Record.create(data, id_=id)
                record['$schema'] = schema
                bucket = Bucket.create()
                RecordsBuckets.create(
                    record=record.model, bucket=bucket)

                for file in files:
                    if skip_files:
                        break
                    assert 'uri' in file
                    assert 'size' in file
                    assert 'checksum' in file

                    f = FileInstance.create()
                    filename = file.get("uri").split('/')[-1:][0]
                    f.set_uri(file.get("uri"), file.get(
                        "size"), file.get("checksum"))

                    ObjectVersion.create(
                        bucket,
                        filename,
                        _file_id=f.id
                    )
                db.session.commit()
                indexer.index(record)
                db.session.expunge_all()


@fixtures.command()
@click.option('--skip-files', is_flag=True, default=False,
              help='Skip loading of files')
@with_appcontext
def software(skip_files):
    """Load demo software records."""
    from invenio_db import db
    from invenio_records_files.api import Record
    from invenio_indexer.api import RecordIndexer
    from cernopendata.modules.records.minters.softid import \
        cernopendata_softid_minter

    from invenio_files_rest.models import \
        Bucket, FileInstance, ObjectVersion
    from invenio_records_files.models import RecordsBuckets

    indexer = RecordIndexer()
    schema = current_app.extensions['invenio-jsonschemas'].path_to_url(
        'records/software-v1.0.0.json'
    )
    data = pkg_resources.resource_filename('cernopendata',
                                           'modules/fixtures/data/software')
    software_json = glob.glob(os.path.join(data, '*.json'))

    for filename in software_json:
        with open(filename, 'rb') as source:
            for data in json.load(source):
                files = data.pop('files', [])

                id = uuid.uuid4()
                cernopendata_softid_minter(id, data)
                record = Record.create(data, id_=id)
                record['$schema'] = schema
                bucket = Bucket.create()
                RecordsBuckets.create(
                    record=record.model, bucket=bucket)

                for file in files:
                    if skip_files:
                        break
                    assert 'uri' in file
                    assert 'size' in file
                    assert 'checksum' in file

                    f = FileInstance.create()
                    filename = file.get("uri").split('/')[-1:][0]
                    f.set_uri(file.get("uri"), file.get(
                        "size"), file.get("checksum"))
                    ObjectVersion.create(
                        bucket,
                        filename,
                        _file_id=f.id
                    )
                db.session.commit()
                indexer.index(record)
                db.session.expunge_all()


@fixtures.command()
@with_appcontext
def pids():
    """Fetch and register PIDs."""
    from invenio_db import db
    from invenio_oaiserver.fetchers import onaiid_fetcher
    from invenio_oaiserver.minters import oaiid_minter
    from invenio_pidstore.errors import PIDDoesNotExistError
    from invenio_pidstore.models import PIDStatus, PersistentIdentifier
    from invenio_pidstore.fetchers import recid_fetcher
    from invenio_records.models import RecordMetadata

    recids = [r.id for r in RecordMetadata.query.all()]
    db.session.expunge_all()

    with click.progressbar(recids) as bar:
        for record_id in bar:
            record = RecordMetadata.query.get(record_id)
            try:
                pid = recid_fetcher(record.id, record.json)
                found = PersistentIdentifier.get(
                    pid_type=pid.pid_type,
                    pid_value=pid.pid_value,
                    pid_provider=pid.provider.pid_provider
                )
                click.echo('Found {0}.'.format(found))
            except PIDDoesNotExistError:
                db.session.add(
                    PersistentIdentifier.create(
                        pid.pid_type, pid.pid_value,
                        object_type='rec', object_uuid=record.id,
                        status=PIDStatus.REGISTERED
                    )
                )
            except KeyError:
                click.echo('Skiped: {0}'.format(record.id))
                continue

            pid_value = record.json.get('_oai', {}).get('id')
            if pid_value is None:
                assert 'control_number' in record.json
                pid_value = current_app.config.get(
                    'OAISERVER_ID_PREFIX'
                ) + str(record.json['control_number'])

                record.json.setdefault('_oai', {})
                record.json['_oai']['id'] = pid.pid_value

            pid = oaiid_fetcher(record.id, record.json)
            try:
                found = PersistentIdentifier.get(
                    pid_type=pid.pid_type,
                    pid_value=pid.pid_value,
                    pid_provider=pid.provider.pid_provider
                )
                click.echo('Found {0}.'.format(found))
            except PIDDoesNotExistError:
                pid = oaiid_minter(record.id, record.json)
                db.session.add(pid)

            flag_modified(record, 'json')
            assert record.json['_oai']['id']
            db.session.add(record)
            db.session.commit()
            db.session.expunge_all()
