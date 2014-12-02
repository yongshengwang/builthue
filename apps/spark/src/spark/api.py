#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging

from django.http import HttpResponse, Http404
from django.utils.translation import ugettext as _

from desktop.context_processors import get_app_name
from desktop.lib.exceptions import StructuredException

from beeswax import models as beeswax_models
from beeswax.views import safe_get_design, save_design

from spark.job_server_api import get_api
from spark.forms import SparkForm, QueryForm
from desktop.lib.i18n import smart_str
from spark.design import SparkDesign
from desktop.lib.rest.http_client import RestException

from spark.decorators import json_error_handler

LOG = logging.getLogger(__name__)

@json_error_handler
def jars(request):
  api = get_api(request.user)
  response = {
    'jars': api.jars()
  }

  return HttpResponse(json.dumps(response), mimetype="application/json")

@json_error_handler
def contexts(request):
  api = get_api(request.user)
  response = {
    'contexts': api.contexts()
  }

  return HttpResponse(json.dumps(response), mimetype="application/json")


def create_context(request):
  if request.method != 'POST':
    raise StructuredException(code="INVALID_REQUEST_ERROR", message=_('Requires a POST'))
  response = {}

  name = request.POST.get('name', '')
  memPerNode = request.POST.get('mem-per-node', '512m')
  numCores = request.POST.get('num-cpu-cores', '1')

  api = get_api(request.user)
  try:
    response = api.create_context(name, memPerNode=memPerNode, numCores=numCores)
  except ValueError:
    # No json is returned
    response = {'status': 'OK'}
  except Exception, e:
    response = json.loads(e.message)

  response['name'] = name

  return HttpResponse(json.dumps(response), mimetype="application/json")


def delete_context(request):
  if request.method != 'DELETE':
    raise StructuredException(code="INVALID_REQUEST_ERROR", message=_('Requires a DELETE'))
  response = {}

  name = request.POST.get('name', '')

  api = get_api(request.user)
  try:
    response = api.delete_context(name)
  except ValueError:
    # No json is returned
    response = {'status': 'OK'}
  except Exception, e:
    response = json.loads(e.message)

  response['name'] = name

  return HttpResponse(json.dumps(response), mimetype="application/json")


def job(request, job_id):
  api = get_api(request.user)
  response = {}
  try:
    response['results'] = api.job(job_id)
  except RestException, e:
    response['results'] = json.loads(e.message)

  return HttpResponse(json.dumps(response), mimetype="application/json")



@json_error_handler
def execute(request, design_id=None):
  response = {'status': -1, 'message': ''}

  if request.method != 'POST':
    response['message'] = _('A POST request is required.')

  app_name = get_app_name(request)
  query_type = beeswax_models.SavedQuery.TYPES_MAPPING[app_name]
  design = safe_get_design(request, query_type, design_id)

  try:
    form = get_query_form(request)

    if form.is_valid():
      #design = save_design(request, SaveForm(), form, query_type, design)

#      query = SQLdesign(form, query_type=query_type)
#      query_server = dbms.get_query_server_config(request.POST.get('server'))
#      db = dbms.get(request.user, query_server)
#      query_history = db.execute_query(query, design)
#      query_history.last_state = beeswax_models.QueryHistory.STATE.expired.index
#      query_history.save()

      params = '\n'.join(['%(name)s=%(value)s' % param for param in json.loads(form.cleaned_data['params'])])

      try:
        api = get_api(request.user)

        results = api.submit_job(
            form.cleaned_data['appName'],
            form.cleaned_data['classPath'],
            data=params,
            context=None if form.cleaned_data['autoContext'] else form.cleaned_data['context'],
            sync=False
        )

        if results['status'] == 'STARTED':
          response['status'] = 0
          response['results'] = results
        else:
          response['message'] = str(results[1]['result'])
        response['design'] = design.id
      except Exception, e:
        response['message'] = str(e)

    else:
      response['message'] = _('There was an error with your query: %s' % form.errors)
      response['errors'] = form.errors
  except RuntimeError, e:
    response['message']= str(e)

  return HttpResponse(json.dumps(response), mimetype="application/json")


@json_error_handler
def save_query(request, design_id=None):
  response = {'status': -1, 'message': ''}

  if request.method != 'POST':
    response['message'] = _('A POST request is required.')

  app_name = get_app_name(request)
  query_type = beeswax_models.SavedQuery.TYPES_MAPPING[app_name]
  design = safe_get_design(request, query_type, design_id)
  form = QueryForm()
  api = get_api(request.user)
  app_names = api.jars()

  try:
    form.bind(request.POST)
    form.query.fields['appName'].choices = ((key, key) for key in app_names)

    if form.is_valid():
      design = save_design(request, form, query_type, design, True)
      response['design_id'] = design.id
      response['status'] = 0
    else:
      response['message'] = smart_str(form.query.errors) + smart_str(form.saveform.errors)
  except RuntimeError, e:
    response['message'] = str(e)

  return HttpResponse(json.dumps(response), mimetype="application/json")


@json_error_handler
def fetch_saved_query(request, design_id):
  response = {'status': -1, 'message': ''}

  if request.method != 'GET':
    response['message'] = _('A GET request is required.')

  app_name = get_app_name(request)
  query_type = beeswax_models.SavedQuery.TYPES_MAPPING[app_name]
  design = safe_get_design(request, query_type, design_id)

  response['design'] = design_to_dict(design)
  return HttpResponse(json.dumps(response), mimetype="application/json")


def design_to_dict(design):
  spark_design = SparkDesign.loads(design.data)
  return {
    'id': design.id,
    'name': design.name,
    'desc': design.desc,
    'appName': spark_design.appName,
    'classPath': spark_design.classPath,
    'autoContext': spark_design.autoContext,
    'context': spark_design.context,
    'params': json.loads(spark_design.params),
  }

def get_query_form(request):
  api = get_api(request.user)

  app_names = api.jars()

  if not app_names:
    raise RuntimeError(_("Missing application jar list."))

  form = SparkForm(request.POST, app_names=app_names)

  return form
