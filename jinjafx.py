#!/usr/bin/env python

# JinjaFx - Jinja Templating Tool
# Copyright (c) 2020-2021 Chris Mason <chris@jinjafx.org>
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

from __future__ import print_function, division
import sys, os, socket, jinja2, yaml, argparse, re, copy, traceback

__version__ = '1.3.3'
jinja2_filters = []

class ArgumentParser(argparse.ArgumentParser):
  def error(self, message):
    if '-q' not in sys.argv:
      print('URL:\n  https://github.com/cmason3/jinjafx\n', file=sys.stderr)
      print('Usage:\n  ' + self.format_usage()[7:], file=sys.stderr)
    raise Exception(message)


def import_filters(errc = 0):
  try:
    from ansible.plugins.filter import core
    jinja2_filters.append(core.FilterModule().filters())
  except Exception:
    print('warning: unable to import ansible \'core\' filters - requires ansible', file=sys.stderr)
    errc += 1
      
  try:
    import netaddr

    try:
      from ansible.plugins.filter import ipaddr
    except Exception:
      try:
        from ansible_collections.ansible.netcommon.plugins.filter import ipaddr
      except Exception:
        raise Exception()

    filters = {}
    for k, v in ipaddr.FilterModule().filters().items():
      filters[k] = v
      filters['ansible.netcommon.' + k] = v

    jinja2_filters.append(filters)

  except Exception:
    print('warning: unable to import ansible \'ipaddr\' filter - requires ansible and netaddr', file=sys.stderr)
    errc += 1

  if errc > 0:
    print()


def main():
  try:
    if '-q' not in sys.argv:
      print('JinjaFx v' + __version__ + ' - Jinja Templating Tool')
      print('Copyright (c) 2020-2021 Chris Mason <chris@jinjafx.org>\n')

    jinjafx_usage = '(-t <template.j2> [-d <data.csv>] | -dt <dt.yml>) [-g <vars.yml>] [-o <output file>] [-od <output dir>] [-m] [-q]'

    parser = ArgumentParser(add_help=False, usage='%(prog)s ' + jinjafx_usage)
    group_ex = parser.add_mutually_exclusive_group(required=True)
    group_ex.add_argument('-dt', metavar='<dt.yml>', type=argparse.FileType('r'))
    group_ex.add_argument('-t', metavar='<template.j2>', type=argparse.FileType('r'))
    parser.add_argument('-d', metavar='<data.csv>', type=argparse.FileType('r'))
    parser.add_argument('-g', metavar='<vars.yml>', type=argparse.FileType('r'), action='append')
    parser.add_argument('-o', metavar='<output file>', type=str)
    parser.add_argument('-od', metavar='<output dir>', type=str)
    parser.add_argument('-m', action='store_true')
    parser.add_argument('-q', action='store_true')
    args = parser.parse_args()

    if args.dt is not None and args.d is not None:
      parser.error("argument -d: not allowed with argument -dt")

    if args.m is True and args.g is None:
      parser.error("argument -m: only allowed with argument -g")

    if args.od is not None and not os.access(args.od, os.W_OK):
      parser.error("argument -od: unable to write to output directory")

    data = None
    vault = [ None ]
    gvars = {}
    dt = {}

    def decrypt_vault(string):
      if string.startswith('$ANSIBLE_VAULT;'):
        if vault[0] is None:
          from ansible.constants import DEFAULT_VAULT_ID_MATCH
          from ansible.parsing.vault import VaultLib
          from ansible.parsing.vault import VaultSecret
          from getpass import getpass

          vpw = os.getenv('ANSIBLE_VAULT_PASSWORD')

          if vpw == None:
            vpwf = os.getenv('ANSIBLE_VAULT_PASSWORD_FILE')
            if vpwf != None:
              with open(vpwf) as f:
                vpw = f.read().strip()

          if vpw == None:
            vpw = getpass('Vault Password: ')
            print()

          vault[0] = VaultLib([(DEFAULT_VAULT_ID_MATCH, VaultSecret(vpw.encode('utf-8')))])

        return vault[0].decrypt(string.encode('utf-8')).decode('utf-8')
      return string

    def yaml_vault_tag(loader, node):
      return decrypt_vault(node.value)

    def merge(dst, src):
      for key in src:
        if key in dst:
          if isinstance(dst[key], dict) and isinstance(src[key], dict):
            merge(dst[key], src[key])

          elif isinstance(dst[key], list) and isinstance(src[key], list):
            dst[key] += src[key]

          else:
            dst[key] = src[key]

        else:
          dst[key] = src[key]

      return dst

    yaml.add_constructor('!vault', yaml_vault_tag, yaml.SafeLoader)

    if args.dt is not None:
      with open(args.dt.name) as f:
        dt.update(yaml.load(f.read(), Loader=yaml.SafeLoader)['dt'])
        args.t = dt['template']

        if 'data' in dt:
          data = dt['data']

        if 'vars' in dt:
          gyaml = decrypt_vault(dt['vars'])
          if gyaml:
            gvars.update(yaml.load(gyaml, Loader=yaml.SafeLoader))

    if args.d is not None:
      with open(args.d.name) as f:
        data = f.read()

    if args.g is not None:
      for g in args.g:
        with open(g.name) as f:
          gyaml = decrypt_vault(f.read())
          if args.m == True:
            merge(gvars, yaml.load(gyaml, Loader=yaml.SafeLoader))
          else:
            gvars.update(yaml.load(gyaml, Loader=yaml.SafeLoader))

    if args.o is None:
      args.o = '_stdout_'

    import_filters()
    outputs = JinjaFx().jinjafx(args.t, data, gvars, args.o)
    ocount = 0

    if args.od is not None:
      os.chdir(args.od)

    for o in sorted(outputs.items(), key=lambda x: (x[0] == '_stdout_')):
      output = '\n'.join(o[1]) + '\n'
      if len(output.strip()) > 0:
        if o[0] != '_stdout_':
          ofile = re.sub(r'_+', '_', re.sub(r'[^A-Za-z0-9_. -/]', '_', os.path.normpath(o[0])))

          if os.path.dirname(ofile) != '':
            if not os.path.isdir(os.path.dirname(ofile)):
              os.makedirs(os.path.dirname(ofile))

          with open(ofile, 'w') as f:
            f.write(output)

          print(format_bytes(len(output)) + ' > ' + ofile)

        else:
          if ocount > 0:
            print('\n-\n')
          print(output)

        ocount += 1

    if ocount > 0:
      if '_stdout_' not in outputs:
        print()
    else:
      raise Exception('nothing to output')

  except KeyboardInterrupt:
    sys.exit(-1)

  except Exception as e:
    tb = traceback.format_exc()
    match = re.search(r'[\s\S]*File "(.+)", line ([0-9]+), in.*template', tb, re.IGNORECASE)
    if match:
      print('error[' + match.group(1) + ':' + match.group(2) + ']: ' + type(e).__name__ + ': ' + str(e), file=sys.stderr)
    else:
      print('error[' + str(sys.exc_info()[2].tb_lineno) + ']: ' + type(e).__name__ + ': ' + str(e), file=sys.stderr)

    sys.exit(-2)


def format_bytes(b):
  for u in [ '', 'k', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y' ]:
    if b >= 1000:
      b /= 1000
    else:
      return '{:.2f}'.format(b).rstrip('0').rstrip('.') + u + 'B'


class JinjaFx():
  def jinjafx(self, template, data, gvars, output):
    self.g_datarows = []
    self.g_dict = {}
    self.g_row = 0 

    outputs = {}
    delim = None
    rowkey = 1
    int_indices = []
    
    if isinstance(data, bytes):
      data = data.decode('utf-8')

    if data is not None and len(data.strip()) > 0:
      jinjafx_filter = {}

      for l in data.splitlines():
        if len(l.strip()) > 0 and not re.match(r'^[ \t]*#', l):
          if len(self.g_datarows) == 0:
            if l.count(',') > l.count('\t'):
              delim = r'[ \t]*,[ \t]*'
              schars = ' \t'
            else:
              delim = r' *\t *'
              schars = ' '

            fields = re.split(delim, re.sub('(?:' + delim + ')+$', '', l.strip(schars)))
            fields = [re.sub(r'^(["\'])(.*)\1$', r'\2', f) for f in fields]

            for i in range(len(fields)):
              if fields[i].lower().endswith(':int'):
                int_indices.append(i + 1)
                fields[i] = fields[i][:-4]

              if 'jinjafx_adjust_headers' in gvars:
                jinjafx_adjust_headers = str(gvars['jinjafx_adjust_headers']).strip().lower()

                if jinjafx_adjust_headers == 'yes':
                  fields[i] = re.sub(r'[^A-Z0-9_]', '', fields[i], flags=re.UNICODE | re.IGNORECASE)

                elif jinjafx_adjust_headers == 'upper':
                  fields[i] = re.sub(r'[^A-Z0-9_]', '', fields[i].upper(), flags=re.UNICODE | re.IGNORECASE)

                elif jinjafx_adjust_headers == 'lower':
                  fields[i] = re.sub(r'[^A-Z0-9_]', '', fields[i].lower(), flags=re.UNICODE | re.IGNORECASE)

                elif jinjafx_adjust_headers != 'no':
                  raise Exception('invalid value specified for \'jinjafx_adjust_headers\' - must be \'yes\', \'no\', \'upper\' or \'lower\'')
              
              if fields[i] == '':
                raise Exception('empty header field detected at column position ' + str(i + 1))
              elif not re.match(r'^[A-Z_][A-Z0-9_]*$', fields[i], re.IGNORECASE):
                raise Exception('header field at column position ' + str(i + 1) + ' contains invalid characters')

            if len(set(fields)) != len(fields):
              raise Exception('duplicate header field detected in data')
            else:
              self.g_datarows.append(fields)

            if 'jinjafx_filter' in gvars and len(gvars['jinjafx_filter']) > 0:
              for field in gvars['jinjafx_filter']:
                jinjafx_filter[self.g_datarows[0].index(field) + 1] = gvars['jinjafx_filter'][field]

          else:
            gcount = 1
            fields = []
            for f in re.split(delim, l.strip(schars)):
              delta = 0

              for m in re.finditer(r'(?<!\\)\((.+?)(?<!\\)\)', f):
                if not re.search(r'(?<!\\)\|', m.group(1)):
                  if not re.search(r'\\' + str(gcount), l):
                    if re.search(r'\\[0-9]+', l):
                      raise Exception('parenthesis in row ' + str(rowkey) + ' at \'' + str(m.group(0)) + '\' should be escaped or removed')
                    else:
                      f = f[:m.start() + delta] + '\\(' + m.group(1) + '\\)' + f[m.end() + delta:]
                      delta += 2

                gcount += 1

              fields.append(re.sub(r'^(["\'])(.*)\1$', r'\2', f))

            n = len(self.g_datarows[0])
            fields = [list(map(self.jfx_expand, fields[:n] + [''] * (n - len(fields)), [True] * n))]

            recm = r'(?<!\\){[ \t]*([0-9]+):([0-9]+)(?::([0-9]+))?[ \t]*(?<!\\)}'

            row = 0
            while row < len(fields):
              if not isinstance(fields[row][0], int):
                fields[row].insert(0, rowkey)
                rowkey += 1

              if any(isinstance(col[0], list) for col in fields[row][1:]):
                for col in range(1, len(fields[row])):
                  if isinstance(fields[row][col][0], list):
                    for v in range(len(fields[row][col][0])):
                      nrow = copy.deepcopy(fields[row])
                      nrow[col] = [fields[row][col][0][v], fields[row][col][1][v]]
                      fields.append(nrow)

                    fields.pop(row)
                    break

              else:
                groups = []

                for col in range(1, len(fields[row])):
                  fields[row][col][0] = re.sub(recm, lambda m: self.jfx_data_counter(m, fields[row][0], col, row), fields[row][col][0])

                  for g in range(len(fields[row][col][1])):
                    fields[row][col][1][g] = re.sub(recm, lambda m: self.jfx_data_counter(m, fields[row][0], col, row), fields[row][col][1][g])

                  groups.append(fields[row][col][1])

                groups = dict(enumerate(sum(groups, ['\\0'])))

                for col in range(1, len(fields[row])):
                  fields[row][col] = re.sub(r'\\([0-9]+)', lambda m: groups.get(int(m.group(1)), '\\' + m.group(1)), fields[row][col][0])
                  fields[row][col] = re.sub(r'\\([}{])', r'\1', fields[row][col])

                  if col in int_indices:
                    fields[row][col] = int(fields[row][col])

                include_row = True
                if len(jinjafx_filter) > 0:
                  for index in jinjafx_filter:
                    if not re.search(jinjafx_filter[index], fields[row][index]):
                      include_row = False
                      break

                if include_row:
                  self.g_datarows.append(fields[row])

                row += 1

      if len(self.g_datarows) <= 1:
        raise Exception('not enough data rows - need at least two')

    if 'jinjafx_sort' in gvars and len(gvars['jinjafx_sort']) > 0:
      for field in reversed(gvars['jinjafx_sort']):
        if isinstance(field, dict):
          fn = next(iter(field))
          r = True if fn.startswith('-') else False
          mv = []

          for rx, v in field[fn].items():
            mv.append([re.compile(rx + '$'), v])

          self.g_datarows[1:] = sorted(self.g_datarows[1:], key=lambda n: (self.find_re_match(mv, n[self.g_datarows[0].index(fn.lstrip('+-')) + 1]), n[self.g_datarows[0].index(fn.lstrip('+-')) + 1]), reverse=r)

        else:
          r = True if field.startswith('-') else False
          self.g_datarows[1:] = sorted(self.g_datarows[1:], key=lambda n: n[self.g_datarows[0].index(field.lstrip('+-')) + 1], reverse=r)

    if 'jinja2_extensions' not in gvars:
      gvars.update({ 'jinja2_extensions': [] })

    jinja2_options = {
      'undefined': jinja2.StrictUndefined,
      'trim_blocks': True,
      'lstrip_blocks': True,
      'keep_trailing_newline': True
    }

    if isinstance(template, bytes) or isinstance(template, str):
      env = jinja2.Environment(extensions=gvars['jinja2_extensions'], **jinja2_options)
      [env.filters.update(f) for f in jinja2_filters]
      if isinstance(template, bytes):
        template = env.from_string(template.decode('utf-8'))
      else:
        template = env.from_string(template)
    else:
      env = jinja2.Environment(extensions=gvars['jinja2_extensions'], loader=jinja2.FileSystemLoader(os.path.dirname(template.name)), **jinja2_options)
      [env.filters.update(f) for f in jinja2_filters]
      template = env.get_template(os.path.basename(template.name))

    env.globals.update({ 'jinjafx': {
      'version': __version__,
      'jinja_version': jinja2.__version__,
      'expand': self.jfx_expand,
      'counter': self.jfx_counter,
      'exception': self.jfx_exception,
      'first': self.jfx_first,
      'last': self.jfx_last,
      'fields': self.jfx_fields,
      'setg': self.jfx_setg,
      'getg': self.jfx_getg,
      'nslookup': self.jfx_nslookup,
      'rows': max([0, len(self.g_datarows) - 1]),
      'data': [r[1:] if isinstance(r[0], int) else r for r in self.g_datarows]
    }})

    if len(gvars) > 0:
      env.globals.update(gvars)

    for row in range(1, max(2, len(self.g_datarows))):
      rowdata = {}

      if len(self.g_datarows) > 0:
        for col in range(len(self.g_datarows[0])):
          rowdata.update({ self.g_datarows[0][col]: self.g_datarows[row][col + 1] })

        env.globals['jinjafx'].update({ 'row': row })
        self.g_row = row

      else:
        env.globals['jinjafx'].update({ 'row': 0 })
        self.g_row = 0

      try:
        content = template.render(rowdata)

      except Exception as e:
        if e.args[0].startswith('[jfx_exception] '):
          e.args = (e.args[0][16:],)
        else:
          if len(e.args) >= 1 and self.g_row != 0:
            e.args = (e.args[0] + ' at data row ' + str(self.g_datarows[row][0]) + ':\n - ' + str(rowdata),) + e.args[1:]
        raise

      stack = ['0:' + env.from_string(output).render(rowdata)]
      for l in iter(content.splitlines()):
        block_begin = re.search(r'<output[\t ]+["\']*(.+?)["\']*[\t ]*>(?:\[(-?\d+)\])?', l, re.IGNORECASE)
        if block_begin:
          if block_begin.group(2) != None:
            index = int(block_begin.group(2))
          else:
            index = 0

          stack.append(str(index) + ':' + block_begin.group(1).strip())
        else:
          block_end = re.search(r'</output[\t ]*>', l, re.IGNORECASE)
          if block_end:
            if len(stack) > 1:
              stack.pop()
            else:
              raise Exception('unbalanced output tags')
          else:
            if stack[-1] not in outputs:
              outputs[stack[-1]] = []
            outputs[stack[-1]].append(l)

      if len(stack) != 1:
        raise Exception('unbalanced output tags')

    for o in sorted(outputs.keys(), key=lambda x: int(x.split(':')[0])):
      nkey = o.split(':')[1]

      if nkey not in outputs:
        outputs[nkey] = []
          
      outputs[nkey] += outputs[o]
      del outputs[o]

    return outputs


  def jfx_data_counter(self, m, orow, col, row):
    start = m.group(1)
    increment = m.group(2)
    pad = int(m.group(3)) if m.lastindex == 3 else 0

    key = '_datacnt_r_' + str(orow) + '_' + str(col) + '_' + m.group()

    if self.g_dict.get(key + '_' + str(row), True):
      n = self.g_dict.get(key, int(start) - int(increment))
      self.g_dict[key] = n + int(increment)
      self.g_dict[key + '_' + str(row)] = False
    return str(self.g_dict[key]).zfill(pad)


  def jfx_expand(self, s, rg=False):
    pofa = [s]
    groups = [[s]]

    if re.search(r'(?<!\\)[\(\[\{]', pofa[0]):
      i = 0
      while i < len(pofa):
        m = re.search(r'(?<!\\)\((.+?)(?<!\\)\)', pofa[i])
        if m:
          for g in re.split(r'(?<!\\)\|', m.group(1)):
            pofa.append(pofa[i][:m.start(1) - 1] + g + pofa[i][m.end(1) + 1:])
            groups.append(groups[i] + [re.sub(r'\\([\|\(\[\)\]])', r'\1', g)])

          pofa.pop(i)
          groups.pop(i)

        else:
          i += 1

      i = 0
      while i < len(pofa):
        m = re.search(r'(?<!\\)\{[ \t]*([0-9]+-[0-9]+):([0-9]+)(?::([0-9]+))?[ \t]*(?<!\\)\}', pofa[i])
        if m:
          mpos = groups[i][0].index(m.group())
          nob = len(re.findall(r'(?<!\\)\(', groups[i][0][:mpos]))
          ncb = len(re.findall(r'(?<!\\)\)', groups[i][0][:mpos]))
          groups[i][0] = groups[i][0].replace(m.group(), 'x', 1)
          group = max(0, (nob - ncb) * nob)

          e = list(map(int, m.group(1).split('-')))

          start = e[0]
          end = e[1] + 1 if e[1] >= e[0] else e[1] - 1
          step = int(m.group(2)) if end > start else 0 - int(m.group(2))

          for n in range(start, end, step):
            n = str(n).zfill(int(m.group(3)) if m.lastindex == 3 else 0)
            pofa.append(pofa[i][:m.start(1) - 1] + n + pofa[i][m.end(m.lastindex) + 1:])

            ngroups = list(groups[i])
            if group > 0 and group < len(ngroups):
              ngroups[group] = ngroups[group].replace(m.group(), n, 1)

            groups.append(ngroups)

          pofa.pop(i)
          groups.pop(i)

        else:
          m = re.search(r'(?<!\\)\[([A-Z0-9\-]+)(?<!\\)\]', pofa[i], re.IGNORECASE)
          if m and not re.match(r'(?:[A-Z]-[^A-Z]|[a-z]-[^a-z]|[0-9]-[^0-9]|[^A-Za-z0-9]-)', m.group(1)):
            clist = []
  
            mpos = groups[i][0].index(m.group())
            nob = len(re.findall(r'(?<!\\)\(', groups[i][0][:mpos]))
            ncb = len(re.findall(r'(?<!\\)\)', groups[i][0][:mpos]))
            groups[i][0] = groups[i][0].replace(m.group(), 'x', 1)
            group = max(0, (nob - ncb) * nob)
  
            for x in re.findall('([A-Z0-9](-[A-Z0-9])?)', m.group(1), re.IGNORECASE):
              if x[1] != '':
                e = x[0].split('-')

                start = ord(e[0])
                end = ord(e[1]) + 1 if ord(e[1]) >= ord(e[0]) else ord(e[1]) - 1
                step = 1 if end > start else -1

                for c in range(start, end, step):
                  clist.append(chr(c))
              else:
                clist.append(x[0])
  
            for c in clist:
              pofa.append(pofa[i][:m.start(1) - 1] + c + pofa[i][m.end(1) + 1:])
              ngroups = list(groups[i])
  
              if group > 0 and group < len(ngroups):
                ngroups[group] = ngroups[group].replace(m.group(), c, 1)
              
              groups.append(ngroups)
  
            pofa.pop(i)
            groups.pop(i)

          else:
            i += 1

    for g in groups:
      g.pop(0)

    pofa = [re.sub(r'\\([\|\(\[\)\]])', r'\1', i) for i in pofa]
    return [pofa, groups] if rg else pofa


  def jfx_fandl(self, forl, fields, ffilter):
    fpos = []

    if self.g_row == 0:
      return True

    if fields is not None:
      for f in fields:
        if f in self.g_datarows[0]:
          fpos.append(self.g_datarows[0].index(f) + 1)
        else:
          raise Exception('invalid field \'' + f + '\' passed to jinjafx.' + forl + '()')
    elif forl == 'first':
      return True if self.g_row == 1 else False
    else:
      return True if self.g_row == (len(self.g_datarows) - 1) else False

    tv = ':'.join([self.g_datarows[self.g_row][i] for i in fpos])

    if forl == 'first':
      rows = range(1, len(self.g_datarows))
    else:
      rows = range(len(self.g_datarows) - 1, 0, -1)

    for r in rows:
      fmatch = True

      for f in ffilter:
        if f in self.g_datarows[0]:
          try:
            if not re.match(ffilter[f], self.g_datarows[r][self.g_datarows[0].index(f) + 1]):
              fmatch = False
              break
          except Exception:
            raise Exception('invalid filter regex \'' + ffilter[f] + '\' for field \'' + f + '\' passed to jinjafx.' + forl + '()')
        else:
          raise Exception('invalid filter field \'' + f + '\' passed to jinjafx.' + forl + '()')

      if fmatch:
        if tv == ':'.join([self.g_datarows[r][i] for i in fpos]):
          return True if self.g_row == r else False

    return False


  def jfx_exception(self, message):
    raise Exception('[jfx_exception] ' + message)


  def jfx_first(self, fields=None, ffilter={}):
    return self.jfx_fandl('first', fields, ffilter)


  def jfx_last(self, fields=None, ffilter={}):
    return self.jfx_fandl('last', fields, ffilter)

  
  def jfx_fields(self, field=None, ffilter={}):
    if field is not None:
      if field in self.g_datarows[0]:
        fpos = self.g_datarows[0].index(field) + 1
      else:
        raise Exception('invalid field \'' + field + '\' passed to jinjafx.fields()')
    else:
      return None
    
    field_values = []
        
    for r in range(1, len(self.g_datarows)):
      fmatch = True
      field_value = self.g_datarows[r][fpos]

      if field_value not in field_values and len(field_value.strip()) > 0:
        for f in ffilter:
          if f in self.g_datarows[0]:
            try:
              if not re.match(ffilter[f], self.g_datarows[r][self.g_datarows[0].index(f) + 1]):
                fmatch = False
                break
            except Exception:
              raise Exception('invalid filter regex \'' + ffilter[f] + '\' for field \'' + f + '\' passed to jinjafx.fields()')
          else:
            raise Exception('invalid filter field \'' + f + '\' passed to jinjafx.fields()')

        if fmatch:
          field_values.append(field_value)
    
    return field_values

 
  def jfx_counter(self, key=None, increment=1, start=1):
    if key is None:
      key = '_cnt_r_' + str(self.g_row)
    else:
      key = '_cnt_k_' + str(key)

    n = self.g_dict.get(key, int(start) - int(increment))
    self.g_dict[key] = n + int(increment)
    return self.g_dict[key]


  def jfx_setg(self, key, value):
    self.g_dict['_val_' + str(key)] = value
    return ''


  def jfx_getg(self, key, default=None):
    return self.g_dict.get('_val_' + str(key), default)


  def jfx_nslookup(self, v, family=46):
    try:
      if re.match(r'^(?:[0-9a-f:]+:+)+[0-9a-f]+$', v, re.I): # IPv6
        return [socket.getnameinfo((v, 0), socket.NI_NAMEREQD)[0]]

      elif re.match(r'^(?:[0-9]+\.){3}[0-9]+$', v): # IPv4
        return [socket.getnameinfo((v, 0), socket.NI_NAMEREQD)[0]]

      else:
        if int(family) == 46:
          s = socket.getaddrinfo(v, 0, 0, socket.SOCK_STREAM)
          return [e[4][0] for e in s]
        elif int(family) == 4:
          s = socket.getaddrinfo(v, 0, socket.AF_INET, socket.SOCK_STREAM)
          return [e[4][0] for e in s]
        elif int(family) == 6:
          s = socket.getaddrinfo(v, 0, socket.AF_INET6, socket.SOCK_STREAM)
          return [e[4][0] for e in s]

    except:
      pass

    return None


  def find_re_match(self, o, v, default=0):
    for rx in o:
      if rx[0].match(v):
        return rx[1]

    return default


if __name__ == '__main__':
  main()
