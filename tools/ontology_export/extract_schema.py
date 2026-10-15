"""Conservative PostgreSQL migration catalog extractor; never executes source SQL.

Source spans survive lexical parsing. Unsupported structural DDL is reported, not
silently approximated. Function bodies and quoted strings are not parsed as DDL.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

DEFAULT_COMMIT='9995fc20cd84093adcaa3fab954ffe9d08b9f45a'
DEFAULT_REPOSITORY='https://github.com/8jdkds7nzz-hub/liangzihu-farm-platform'

@dataclass
class Token:
    text:str
    start:int
    end:int
    kind:str='word'
    @property
    def upper(self):return self.text.upper()


def lex(sql):
    tokens=[];i=0;n=len(sql)
    while i<n:
        if sql[i].isspace():i+=1;continue
        if sql.startswith('--',i):
            end=sql.find('\n',i);i=n if end<0 else end+1;continue
        if sql.startswith('/*',i):
            depth=1;i+=2
            while i<n and depth:
                if sql.startswith('/*',i):depth+=1;i+=2
                elif sql.startswith('*/',i):depth-=1;i+=2
                else:i+=1
            if depth:raise ValueError('Unclosed block comment')
            continue
        start=i;char=sql[i]
        if char in "'\"":
            quote_char=char;i+=1
            while i<n:
                if sql[i]==quote_char:
                    if i+1<n and sql[i+1]==quote_char:i+=2;continue
                    i+=1;break
                if sql[i]==chr(92) and quote_char=="'" and start>0 and sql[start-1] in 'Ee':i+=2
                else:i+=1
            else:raise ValueError('Unclosed SQL string/identifier')
            tokens.append(Token(sql[start:i],start,i,'string' if char=="'" else 'identifier'));continue
        if char=='$':
            match=re.match(r'\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$',sql[i:])
            if match:
                tag=match.group();end=sql.find(tag,i+len(tag))
                if end<0:raise ValueError('Unclosed dollar-quoted body')
                i=end+len(tag);tokens.append(Token(sql[start:i],start,i,'body'));continue
        match=re.match(r'[A-Za-z_][A-Za-z_0-9$]*',sql[i:])
        if match:
            i+=len(match.group());tokens.append(Token(sql[start:i],start,i));continue
        match=re.match(r'\d+(?:\.\d+)?',sql[i:])
        if match:
            i+=len(match.group());tokens.append(Token(sql[start:i],start,i,'number'));continue
        i+=1;tokens.append(Token(char,start,i,'punct'))
    return tokens


def statements(tokens):
    part=[]
    for token in tokens:
        if token.text==';':
            if part:yield part
            part=[]
        else:part.append(token)
    if part:yield part


def segments(tokens,separator=','):
    result=[];start=0;depth=0
    for i,token in enumerate(tokens):
        if token.text in {'(','['}:depth+=1
        elif token.text in {')',']'}:depth-=1
        elif token.text==separator and depth==0:result.append(tokens[start:i]);start=i+1
    result.append(tokens[start:]);return [part for part in result if part]


def parenthesized(tokens,start):
    if start>=len(tokens) or tokens[start].text!='(':raise ValueError('Expected opening parenthesis')
    depth=1
    for end in range(start+1,len(tokens)):
        if tokens[end].text=='(':depth+=1
        elif tokens[end].text==')':
            depth-=1
            if depth==0:return tokens[start+1:end],end+1
    raise ValueError('Unclosed parentheses')


def identifier(token):
    if token.kind=='identifier':return token.text[1:-1].replace('""','"')
    if token.kind!='word':raise ValueError('Expected identifier, got '+token.text)
    return token.text.lower()


def qualified(tokens,start=0):
    parts=[identifier(tokens[start])];position=start+1
    while position+1<len(tokens) and tokens[position].text=='.':
        parts.append(identifier(tokens[position+1]));position+=2
    return '.'.join(parts),position


def column_names(tokens):
    result=[]
    for segment in segments(tokens):
        if len(segment)!=1:raise ValueError('Expected plain column identifiers')
        result.append(identifier(segment[0]))
    return result


def sql_string(token):
    if token.kind!='string':raise ValueError('Expected literal SQL string')
    return token.text[1:-1].replace("''", "'")


def strip_outer(tokens):
    while tokens and tokens[0].text=='(':
        inside,end=parenthesized(tokens,0)
        if end!=len(tokens):break
        tokens=inside
    return tokens


class Extractor:
    def __init__(self,repository=DEFAULT_REPOSITORY,commit=DEFAULT_COMMIT,path_prefix='db/migrations'):
        self.repository=repository.rstrip('/');self.commit=commit;self.path_prefix=path_prefix.strip('/')
        self.tables={};self.dropped_tables=[];self.enum_types={};self.indexes=[];self.dropped_indexes=[]
        self.ddl_audit=[];self.unparsed=[];self.other_statements=[];self.files=[];self.file_sql='';self.file_path=''

    def raw(self,tokens):
        return self.file_sql[tokens[0].start:tokens[-1].end] if tokens else ''

    def source(self,tokens):
        start=tokens[0].start if tokens else 0;end=tokens[-1].end if tokens else start
        line=self.file_sql.count('\n',0,start)+1;endline=self.file_sql.count('\n',0,end)+1
        return {'path':self.file_path,'line':line,'end_line':endline,'url':self.repository+'/blob/'+self.commit+'/'+quote(self.file_path,safe='/')+'#L'+str(line)}

    def unresolved(self,tokens,reason,context=None):
        row={'source':self.source(tokens),'sql':self.raw(tokens),'reason':reason}
        if context:row['context']=context
        self.unparsed.append(row);return row

    def table(self,name):
        if name in self.tables:return self.tables[name]
        if name.startswith('public.') and name[7:] in self.tables:return self.tables[name[7:]]
        if 'public.'+name in self.tables:return self.tables['public.'+name]
        raise ValueError('Referenced table is absent in collected migration sequence: '+name)

    def new_table(self,name,tokens):
        if name in self.tables:raise ValueError('CREATE TABLE duplicates active table '+name)
        table={'name':name.rsplit('.',1)[-1],'schema':name.rsplit('.',1)[0] if '.' in name else 'public','qualified_name':name,
               'source':self.source(tokens),'columns':[],'primary_key':[],'constraints':[],'foreign_keys':[],'indexes':[],'history':[],'dropped_columns':[]}
        self.tables[name]=table;return table

    def column(self,table,name):
        for column in table['columns']:
            if column['name']==name:return column
        raise ValueError('Column is absent: '+table['qualified_name']+'.'+name)

    def constraint_name(self,table,kind,columns,name=None):
        if name:return name,False
        suffix={'primary_key':'pkey','unique':'key','foreign_key':'fkey','check':'check'}.get(kind,kind)
        base=table['name']+('_'+'_'.join(columns) if columns and kind!='primary_key' else '')+'_'+suffix
        candidate=base;number=1
        while any(c['name']==candidate for c in table['constraints']):candidate=base+str(number);number+=1
        return candidate,True

    def add_constraint(self,table,kind,tokens,columns=None,name=None,**details):
        columns=columns or [];resolved,inferred=self.constraint_name(table,kind,columns,name)
        if any(c['name']==resolved for c in table['constraints']):raise ValueError('Duplicate active constraint '+resolved)
        result={'name':resolved,'kind':kind,'columns':columns,'name_inferred':inferred,'definition':self.raw(tokens),'source':self.source(tokens),**details}
        table['constraints'].append(result)
        return result

    def parse_reference(self,tokens,start):
        name,position=qualified(tokens,start);columns=[]
        if position<len(tokens) and tokens[position].text=='(':
            body,position=parenthesized(tokens,position);columns=column_names(body)
        tail=tokens[position:];words=' '.join(t.upper for t in tail)
        options={}
        for action in ['DELETE','UPDATE']:
            match=re.search(r'\bON '+action+r' (NO ACTION|RESTRICT|CASCADE|SET NULL|SET DEFAULT)\b',words)
            options['on_'+action.lower()]=match.group(1) if match else 'NO ACTION'
        options['not_valid']='NOT VALID' in words
        options['deferrable']='DEFERRABLE' in words and 'NOT DEFERRABLE' not in words
        return {'referenced_table':name,'referenced_columns':columns,**options}

    def parse_constraint(self,table,tokens,inline_column=None):
        position=0;name=None
        if tokens[0].upper=='CONSTRAINT':name=identifier(tokens[1]);position=2
        kind=tokens[position].upper
        if kind in {'PRIMARY','UNIQUE','FOREIGN'}:
            target={'PRIMARY':'primary_key','UNIQUE':'unique','FOREIGN':'foreign_key'}[kind]
            position+=2 if kind in {'PRIMARY','FOREIGN'} else 1
            if position<len(tokens) and tokens[position].upper=='NULLS':
                position+=3 if tokens[position+1].upper=='NOT' else 2
            if inline_column:columns=[inline_column]
            else:
                body,position=parenthesized(tokens,position);columns=column_names(body)
            if target=='foreign_key':
                if tokens[position].upper!='REFERENCES':raise ValueError('Foreign key lacks REFERENCES')
                reference=self.parse_reference(tokens,position+1)
                return self.add_constraint(table,target,tokens,columns,name,**reference)
            return self.add_constraint(table,target,tokens,columns,name)
        if kind=='REFERENCES' and inline_column:
            return self.add_constraint(table,'foreign_key',tokens,[inline_column],name,**self.parse_reference(tokens,position+1))
        if kind=='CHECK':
            body,end=parenthesized(tokens,position+1)
            expression=self.raw(body);refs=[]
            known={c['name'] for c in table['columns']}
            for token in body:
                if token.kind in {'word','identifier'}:
                    value=identifier(token)
                    if value in known and value not in refs:refs.append(value)
            if inline_column and inline_column not in refs:refs.insert(0,inline_column)
            return self.add_constraint(table,'check',tokens,refs,name,expression=expression,not_valid=any(t.upper=='VALID' for t in tokens[end:]))
        raise ValueError('Unsupported table/column constraint '+self.raw(tokens))

    def inline_reference_end(self,tokens,start):
        _,position=qualified(tokens,start+1)
        if position<len(tokens) and tokens[position].text=='(':_,position=parenthesized(tokens,position)
        while position<len(tokens):
            word=tokens[position].upper
            if word=='ON' and position+2<len(tokens) and tokens[position+1].upper in {'UPDATE','DELETE'}:
                position+=2
                if tokens[position].upper in {'SET','NO'}:position+=2
                else:position+=1
                if position<len(tokens) and tokens[position].text=='(':_,position=parenthesized(tokens,position)
            elif word=='MATCH':position+=2
            elif word=='DEFERRABLE':position+=1
            elif word=='NOT' and position+1<len(tokens) and tokens[position+1].upper in {'VALID','DEFERRABLE'}:position+=2
            elif word=='INITIALLY':position+=2
            else:break
        return position

    def parse_column(self,table,tokens):
        name=identifier(tokens[0]);position=1;depth=0;boundary=len(tokens)
        starters={'CONSTRAINT','NOT','NULL','DEFAULT','PRIMARY','UNIQUE','REFERENCES','CHECK','GENERATED','COLLATE'}
        for i in range(position,len(tokens)):
            token=tokens[i]
            if token.text in {'(','['}:depth+=1
            elif token.text in {')',']'}:depth-=1
            elif depth==0 and token.upper in starters:boundary=i;break
        if boundary==1:raise ValueError('Column has no SQL type '+name)
        if any(c['name']==name for c in table['columns']):raise ValueError('Duplicate column '+name)
        column={'name':name,'sql_type':self.raw(tokens[1:boundary]),'nullable':True,'default':None,'primary_key':False,'unique':False,
                'checks':[],'enum_values':[],'source':self.source(tokens),'history':[]}
        table['columns'].append(column)
        position=boundary
        while position<len(tokens):
            first=position;word=tokens[position].upper
            if word=='NOT' and position+1<len(tokens) and tokens[position+1].upper=='NULL':column['nullable']=False;position+=2;continue
            if word=='NULL':column['nullable']=True;position+=1;continue
            if word=='COLLATE':
                value,end=qualified(tokens,position+1);column['collation']=value;position=end;continue
            if word=='DEFAULT':
                depth=0;end=position+1
                while end<len(tokens):
                    token=tokens[end]
                    if token.text in {'(','['}:depth+=1
                    elif token.text in {')',']'}:depth-=1
                    elif depth==0 and token.upper in starters-{'NULL','DEFAULT'}:break
                    end+=1
                column['default']=self.raw(tokens[position+1:end]);position=end;continue
            if word=='GENERATED':
                column['generated']=self.raw(tokens[position:]);break
            # Inline constraint consumes precisely its own clause. REFERENCES
            # action options continue until the next column constraint starter.
            pos=position+2 if word=='CONSTRAINT' else position
            cword=tokens[pos].upper
            if cword=='PRIMARY':end=pos+2
            elif cword=='UNIQUE':end=pos+1
            elif cword=='CHECK':_,end=parenthesized(tokens,pos+1)
            elif cword=='REFERENCES':end=self.inline_reference_end(tokens,pos)
            else:raise ValueError('Unsupported column clause '+self.raw(tokens[position:]))
            self.parse_constraint(table,tokens[first:end],inline_column=name);position=end
        return column

    def parse_create_table(self,tokens):
        position=next(i for i,t in enumerate(tokens) if t.upper=='TABLE')+1
        optional=[t.upper for t in tokens[position:position+3]]==['IF','NOT','EXISTS']
        if optional:position+=3
        name,position=qualified(tokens,position)
        if optional and name in self.tables:return {'object':name,'operation':'create_table','skipped_existing':True}
        if position>=len(tokens) or tokens[position].text!='(':raise ValueError('CREATE TABLE AS/LIKE/non-column-list not supported')
        body,end=parenthesized(tokens,position)
        table=self.new_table(name,tokens);pending=[]
        for part in segments(body):
            if part[0].upper in {'CONSTRAINT','PRIMARY','UNIQUE','FOREIGN','CHECK','EXCLUDE'}:pending.append(part)
            else:self.parse_column(table,part)
        for part in pending:self.parse_constraint(table,part)
        if end<len(tokens):
            suffix=self.raw(tokens[end:]);table['table_options']=suffix
            # Physical storage/partition metadata is retained, never treated as
            # ordinary columns. Unknown inheritance/typed-table DDL is explicit.
            if any(t.upper in {'INHERITS','OF'} for t in tokens[end:]):raise ValueError('Unsupported inherited/typed-table suffix '+suffix)
        return {'object':name,'operation':'create_table'}

    def parse_alter_part(self,table,tokens):
        word=tokens[0].upper;name=table['qualified_name'];info={'operation':word.lower(),'sql':self.raw(tokens),'source':self.source(tokens)}
        if word=='ADD':
            position=1
            if tokens[position].upper=='COLUMN':position+=1
            optional=[t.upper for t in tokens[position:position+3]]==['IF','NOT','EXISTS']
            if optional:position+=3
            if optional and any(c['name']==identifier(tokens[position]) for c in table['columns']):return dict(info,operation='add_column',skipped_existing=True)
            if tokens[position].upper in {'CONSTRAINT','PRIMARY','UNIQUE','FOREIGN','CHECK','EXCLUDE'}:
                self.parse_constraint(table,tokens[position:]);info['operation']='add_constraint'
            else:self.parse_column(table,tokens[position:]);info['operation']='add_column'
        elif word=='DROP':
            position=1;kind=tokens[position].upper
            if kind in {'COLUMN','CONSTRAINT'}:position+=1
            else:kind='COLUMN'
            optional=[t.upper for t in tokens[position:position+2]]==['IF','EXISTS']
            if optional:position+=2
            target=identifier(tokens[position])
            collection=table['columns'] if kind=='COLUMN' else table['constraints']
            if optional and not any(c['name']==target for c in collection):return dict(info,operation='drop_'+kind.lower(),skipped_absent=True)
            if kind=='COLUMN':
                column=self.column(table,target);table['columns'].remove(column);column['dropped_at']=self.source(tokens);table['dropped_columns'].append(column)
                table['constraints']=[c for c in table['constraints'] if target not in c['columns']]
                for index in list(table['indexes']):
                    if target in index.get('referenced_columns',index['columns']):
                        table['indexes'].remove(index);self.indexes.remove(index);self.dropped_indexes.append(dict(index,dropped_at=self.source(tokens)))
                # Referencing constraints depend on the dropped column too.
                for other in self.tables.values():
                    for c in list(other['constraints']):
                        if c['kind']=='foreign_key' and c['referenced_table']==name and target in c['referenced_columns']:
                            if not any(t.upper=='CASCADE' for t in tokens):raise ValueError('DROP COLUMN without CASCADE has referencing FK '+c['name'])
                            other['constraints'].remove(c)
            else:
                matches=[c for c in table['constraints'] if c['name']==target]
                if not matches:raise ValueError('DROP CONSTRAINT target not found '+target)
                table['constraints'].remove(matches[0])
            info['operation']='drop_'+kind.lower();info['target']=target
        elif word=='ALTER':
            position=1
            if tokens[position].upper=='COLUMN':position+=1
            target=identifier(tokens[position]);column=self.column(table,target);tail=tokens[position+1:]
            commands=[t.upper for t in tail]
            if commands[:2]==['SET','DEFAULT']:column['default']=self.raw(tail[2:]);operation='set_default'
            elif commands[:2]==['DROP','DEFAULT']:column['default']=None;operation='drop_default'
            elif commands[:3]==['SET','NOT','NULL']:column['nullable']=False;operation='set_not_null'
            elif commands[:3]==['DROP','NOT','NULL']:column['nullable']=True;operation='drop_not_null'
            elif commands and (commands[0]=='TYPE' or commands[:3]==['SET','DATA','TYPE']):
                begin=1 if commands[0]=='TYPE' else 3;end=next((i for i,t in enumerate(tail[begin:],begin) if t.upper=='USING'),len(tail))
                column['sql_type']=self.raw(tail[begin:end]);operation='alter_type'
                if end<len(tail):column['using_expression']=self.raw(tail[end+1:])
            else:raise ValueError('Unsupported ALTER COLUMN action '+self.raw(tail))
            info['operation']=operation;info['column']=target;column['history'].append(info)
        elif word=='RENAME':
            position=1;kind=tokens[position].upper
            if kind in {'COLUMN','CONSTRAINT'}:position+=1
            if tokens[position].upper=='TO':
                target=identifier(tokens[position+1]);old=table['qualified_name'];new=(old.rsplit('.',1)[0]+'.' if '.' in old else '')+target
                if new in self.tables:raise ValueError('RENAME table collision '+new)
                self.tables.pop(old);self.tables[new]=table;table['qualified_name']=new;table['name']=target
                for index in table['indexes']:index['table']=new
                for other in self.tables.values():
                    for c in other['constraints']:
                        if c.get('referenced_table')==old:c['referenced_table']=new
                info.update(operation='rename_table',old=old,new=new)
            else:
                old=identifier(tokens[position]);target=identifier(tokens[position+2])
                if tokens[position+1].upper!='TO':raise ValueError('Invalid RENAME action')
                if kind=='CONSTRAINT':
                    constraint=next((c for c in table['constraints'] if c['name']==old),None)
                    if not constraint:raise ValueError('Unknown constraint '+old)
                    constraint['name']=target;constraint['name_inferred']=False
                else:
                    column=self.column(table,old)
                    if any(c['name']==target for c in table['columns']):raise ValueError('Column rename collision')
                    column['name']=target
                    for index in table['indexes']:
                        index['columns']=[target if x==old else x for x in index['columns']]
                        index['referenced_columns']=[target if x==old else x for x in index.get('referenced_columns',[])]
                    for other in self.tables.values():
                        for c in other['constraints']:
                            if other is table:
                                c['columns']=[target if x==old else x for x in c['columns']]
                                if c['kind']=='check':
                                    expression=c['expression'];replacements=[]
                                    for token in lex(expression):
                                        if token.kind in {'word','identifier'} and identifier(token)==old:
                                            replacements.append((token.start,token.end,'"'+target.replace('"','""')+'"' if token.kind=='identifier' else target))
                                    for start,end,value in reversed(replacements):expression=expression[:start]+value+expression[end:]
                                    c.setdefault('original_expression',c['expression']);c['expression']=expression
                            if c.get('referenced_table')==name:c['referenced_columns']=[target if x==old else x for x in c['referenced_columns']]
                info.update(operation='rename_'+('constraint' if kind=='CONSTRAINT' else 'column'),old=old,new=target)
        elif word=='VALIDATE' and tokens[1].upper=='CONSTRAINT':
            target=identifier(tokens[2]);constraint=next((c for c in table['constraints'] if c['name']==target),None)
            if not constraint:raise ValueError('VALIDATE unknown constraint '+target)
            constraint['not_valid']=False;info['operation']='validate_constraint'
        elif word in {'ENABLE','DISABLE','FORCE','NO','OWNER','SET','RESET'}:
            upper=[t.upper for t in tokens]
            auxiliary=(word in {'ENABLE','DISABLE'} and tokens[1].upper in {'TRIGGER','ROW','RULE'}) or (word=='FORCE' and upper[1:4]==['ROW','LEVEL','SECURITY']) or (word=='NO' and upper[1:5]==['FORCE','ROW','LEVEL','SECURITY']) or (word=='OWNER' and upper[1]=='TO') or (word in {'SET','RESET'} and tokens[1].text=='(')
            if not auxiliary:raise ValueError('Unsupported structural table option '+self.raw(tokens))
            info['operation']='table_option';table.setdefault('options_history',[]).append(info)
        else:raise ValueError('Unsupported ALTER TABLE action '+self.raw(tokens))
        table['history'].append(info);return info

    def parse_alter_table(self,tokens):
        position=2
        if [t.upper for t in tokens[position:position+2]]==['IF','EXISTS']:position+=2
        if tokens[position].upper=='ONLY':position+=1
        name,position=qualified(tokens,position);table=self.table(name);parts=[]
        for part in segments(tokens[position:]):
            try:parts.append(dict(self.parse_alter_part(table,part),status='parsed'))
            except (ValueError,IndexError) as exc:
                self.unresolved(part,str(exc),name);parts.append({'status':'unparsed','sql':self.raw(part),'reason':str(exc),'source':self.source(part)})
        return {'object':name,'operation':'alter_table','parts':parts,'status':'partial' if any(p['status']=='unparsed' for p in parts) else 'parsed'}

    def parse_enum(self,tokens,alter=False):
        name,position=qualified(tokens,2)
        if not alter:
            if [t.upper for t in tokens[position:position+2]]!=['AS','ENUM']:raise ValueError('Only CREATE TYPE AS ENUM cataloged')
            body,end=parenthesized(tokens,position+2);values=[sql_string(p[0]) for p in segments(body) if len(p)==1]
            if len(values)!=len(segments(body)):raise ValueError('Nonliteral enum value')
            self.enum_types[name]={'name':name,'values':values,'source':self.source(tokens),'history':[]}
        else:
            if name not in self.enum_types:raise ValueError('ALTER TYPE enum is absent '+name)
            enum=self.enum_types[name];tail=tokens[position:]
            if [t.upper for t in tail[:2]]==['ADD','VALUE']:
                i=2
                if [t.upper for t in tail[i:i+3]]==['IF','NOT','EXISTS']:i+=3
                value=sql_string(tail[i]);i+=1
                if value not in enum['values']:
                    at=len(enum['values'])
                    if i<len(tail) and tail[i].upper in {'BEFORE','AFTER'}:
                        at=enum['values'].index(sql_string(tail[i+1]))+(tail[i].upper=='AFTER')
                    enum['values'].insert(at,value)
            elif [t.upper for t in tail[:2]]==['RENAME','VALUE']:
                old=sql_string(tail[2]);new=sql_string(tail[4]);enum['values'][enum['values'].index(old)]=new
            else:raise ValueError('Unsupported ALTER TYPE action')
            enum['history'].append({'source':self.source(tokens),'sql':self.raw(tokens)})
        return {'operation':'alter_enum' if alter else 'create_enum','object':name}

    def parse_index(self,tokens):
        words=[t.upper for t in tokens];position=words.index('INDEX')+1
        if tokens[position].upper=='CONCURRENTLY':position+=1
        if [t.upper for t in tokens[position:position+3]]==['IF','NOT','EXISTS']:position+=3
        name,position=qualified(tokens,position)
        if tokens[position].upper!='ON':raise ValueError('Index missing ON')
        position+=1
        if tokens[position].upper=='ONLY':position+=1
        table_name,position=qualified(tokens,position);table=self.table(table_name);method='btree'
        if tokens[position].upper=='USING':method=identifier(tokens[position+1]);position+=2
        body,end=parenthesized(tokens,position);expressions=[self.raw(p) for p in segments(body)]
        try:columns=column_names(body)
        except ValueError:columns=[]
        where=next((i for i,t in enumerate(tokens[end:],end) if t.upper=='WHERE'),None)
        record={'name':name,'table':table_name,'unique':'UNIQUE' in words[:words.index('INDEX')],'method':method,'columns':columns,'expressions':expressions,
                'where':self.raw(tokens[where+1:]) if where is not None else None,'source':self.source(tokens),'sql':self.raw(tokens),
                'referenced_columns':list(dict.fromkeys(identifier(t) for t in body if t.kind in {'word','identifier'} and any(c['name']==identifier(t) for c in table['columns'])))}
        self.indexes.append(record);table['indexes'].append(record);return {'operation':'create_index','object':name}

    def process_statement(self,tokens):
        words=[t.upper for t in tokens];start=words[:4];operation=' '.join(words[:2]);is_structural=False
        try:
            if words[0]=='CREATE' and 'TABLE' in words[:4]:is_structural=True;result=self.parse_create_table(tokens)
            elif words[:2]==['ALTER','TABLE']:is_structural=True;result=self.parse_alter_table(tokens)
            elif words[:2]==['CREATE','TYPE']:
                is_structural=True;result=self.parse_enum(tokens)
            elif words[:2]==['ALTER','TYPE']:is_structural=True;result=self.parse_enum(tokens,True)
            elif words[0]=='CREATE' and 'INDEX' in words[:4]:is_structural=True;result=self.parse_index(tokens)
            elif words[:2]==['DROP','INDEX']:
                is_structural=True;position=2
                if tokens[position].upper=='CONCURRENTLY':position+=1
                optional=words[position:position+2]==['IF','EXISTS']
                if optional:position+=2
                name,_=qualified(tokens,position);matches=[i for i in self.indexes if i['name']==name]
                if not matches and not optional:raise ValueError('DROP INDEX target absent '+name)
                for index in matches:
                    self.indexes.remove(index);self.table(index['table'])['indexes'].remove(index);self.dropped_indexes.append(dict(index,dropped_at=self.source(tokens)))
                result={'operation':'drop_index','object':name}
            elif words[:2]==['DROP','TABLE']:
                is_structural=True;position=2
                if words[position:position+2]==['IF','EXISTS']:position+=2
                name,_=qualified(tokens,position);table=self.table(name);self.tables.pop(table['qualified_name']);table['dropped_at']=self.source(tokens);self.dropped_tables.append(table)
                result={'operation':'drop_table','object':name}
            else:
                self.other_statements.append({'kind':operation,'source':self.source(tokens),'sql':self.raw(tokens),
                    'classification':'excluded_from_table_catalog','reason':'function/trigger/security/extension/data statement retained; not interpreted as table definitions'})
                # All ALTER commands are audited even if outside table scope.
                if words[0]=='ALTER':self.ddl_audit.append({'status':'out_of_scope','operation':operation,'source':self.source(tokens),'sql':self.raw(tokens)})
                return
            self.ddl_audit.append({'status':result.pop('status','parsed'),**result,'source':self.source(tokens),'sql':self.raw(tokens)})
        except (ValueError,IndexError,KeyError) as exc:
            self.unresolved(tokens,str(exc));self.ddl_audit.append({'status':'unparsed','operation':operation,'source':self.source(tokens),'sql':self.raw(tokens),'reason':str(exc)})

    def add_file(self,path,relative):
        content=Path(path).read_bytes();sql=content.decode('utf-8-sig')
        self.file_sql=sql;self.file_path=(self.path_prefix+'/' if self.path_prefix else '')+relative.replace(chr(92),'/')
        before=len(self.ddl_audit);unparsed=len(self.unparsed)
        try:
            parsed_statements=list(statements(lex(sql)))
            for statement in parsed_statements:self.process_statement(statement)
        except ValueError as exc:
            self.unparsed.append({'source':{'path':self.file_path,'line':1,'url':self.repository+'/blob/'+self.commit+'/'+self.file_path},'sql':sql,'reason':'Lexical error: '+str(exc)})
            parsed_statements=[]
        self.files.append({'path':self.file_path,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),'statements':len(parsed_statements),'ddl_count':len(self.ddl_audit)-before,'unparsed_count':len(self.unparsed)-unparsed})

    def finalize(self):
        unresolved_references=[]
        for table in self.tables.values():
            for column in table['columns']:
                column['checks']=[];column['enum_values']=[];column['primary_key']=False;column['unique']=False
                enum=self.enum_types.get(column['sql_type']) or self.enum_types.get('public.'+column['sql_type'])
                if enum:column['enum_values']=list(enum['values']);column['enum_source']=enum['source'];column['enum_origin']='CREATE TYPE'
            table['primary_key']=[];table['foreign_keys']=[]
            for constraint in table['constraints']:
                kind=constraint['kind'];columns=constraint['columns']
                for name in columns:
                    if not any(c['name']==name for c in table['columns']):unresolved_references.append({'table':table['qualified_name'],'constraint':constraint['name'],'missing_column':name})
                if kind=='primary_key':
                    table['primary_key']=columns
                    for name in columns:
                        column=self.column(table,name);column['primary_key']=True;column['nullable']=False
                elif kind=='unique' and len(columns)==1:self.column(table,columns[0])['unique']=True
                elif kind=='foreign_key':
                    fk={**constraint,'table':table['qualified_name']};table['foreign_keys'].append(fk)
                    try:
                        target=self.table(fk['referenced_table'])
                        if not fk['referenced_columns']:fk['referenced_columns']=target['primary_key'] or next((c['columns'] for c in target['constraints'] if c['kind']=='primary_key'),[])
                        missing=[name for name in fk['referenced_columns'] if not any(c['name']==name for c in target['columns'])]
                        if missing:unresolved_references.append({'table':table['qualified_name'],'constraint':constraint['name'],'referenced_table':target['qualified_name'],'missing_columns':missing})
                        if len(columns)!=len(fk['referenced_columns']):unresolved_references.append({'table':table['qualified_name'],'constraint':constraint['name'],'reason':'FK column count mismatch'})
                    except ValueError:
                        unresolved_references.append({'table':table['qualified_name'],'constraint':constraint['name'],'missing_table':fk['referenced_table']})
                elif kind=='check':
                    for name in columns:self.column(table,name)['checks'].append({'name':constraint['name'],'expression':constraint['expression'],'source':constraint['source']})
                    # Only an entire direct membership CHECK establishes a
                    # complete vocabulary. Conditional/cross-field checks remain raw.
                    expression=strip_outer(lex(constraint['expression']))
                    if len(expression)>=4 and expression[0].kind in {'word','identifier'} and expression[1].upper=='IN' and expression[2].text=='(':
                        body,end=parenthesized(expression,2)
                        if end==len(expression):
                            pieces=segments(body)
                            if all(len(p)==1 and p[0].kind=='string' for p in pieces):
                                name=identifier(expression[0])
                                if any(c['name']==name for c in table['columns']):
                                    column=self.column(table,name);values=[sql_string(p[0]) for p in pieces]
                                    column['enum_values']=values if not column['enum_values'] else [v for v in column['enum_values'] if v in values]
                                    column['enum_source']=constraint['source'];column['enum_origin']='direct CHECK IN'
            for index in table['indexes']:
                if index['unique'] and not index['where'] and len(index['columns'])==1:
                    self.column(table,index['columns'][0])['unique']=True
        all_tables=list(self.tables.values())
        structural=[a for a in self.ddl_audit if a['operation'] in {'create_table','alter_table'} or a['operation'].upper().startswith(('CREATE TABLE','ALTER TABLE'))]
        return {'schema_version':'liangzihu-schema-catalog/1','source':{'repository':self.repository,'commit':self.commit,'migration_files':len(self.files),'source_kind':'repository DDL only; no live database read','hash_scope':'SHA256 of supplied local text files; Git blob original byte identity not verified'},
                'counts':{'tables':len(all_tables),'columns':sum(len(t['columns']) for t in all_tables),'foreign_keys':sum(len(t['foreign_keys']) for t in all_tables),'constraints':sum(len(t['constraints']) for t in all_tables),'indexes':len(self.indexes),'enum_types':len(self.enum_types),'table_ddl_statements':len(structural),'unparsed_ddl':len(self.unparsed),'unresolved_references':len(unresolved_references)},
                'coverage':{'all_structural_ddl_parsed':not self.unparsed,'all_references_resolved':not unresolved_references,'git_blob_byte_identity_verified':False,'table_ddl_audit_count':len(structural),'lexical_note':'comments, SQL strings and dollar-quoted function bodies are not mistaken for top-level DDL'},
                'files':self.files,'tables':all_tables,'dropped_tables':self.dropped_tables,'dropped_indexes':self.dropped_indexes,'enum_types':list(self.enum_types.values()),'ddl_audit':self.ddl_audit,'unparsed_ddl':self.unparsed,'unresolved_references':unresolved_references,'other_statements':self.other_statements,
                'limitations':['这是源码结构目录，不证明迁移已在现场执行','非简单CHECK保留表达式，不自动推导业务真值/因果','动态函数体DDL不展开，触发器与数据更改仅在other_statements保留','未解析DDL与缺失引用必须复核，不能将部分目录冒充完整生产架构']}


def extract(source,commit=DEFAULT_COMMIT,repository=DEFAULT_REPOSITORY,path_prefix='db/migrations'):
    folder=Path(source);extractor=Extractor(repository,commit,path_prefix)
    files=sorted(folder.rglob('*.sql'),key=lambda p:p.relative_to(folder).as_posix())
    if not files:raise ValueError('No SQL files found')
    for path in files:extractor.add_file(path,path.relative_to(folder).as_posix())
    return extractor.finalize()


def main(argv=None):
    parser=argparse.ArgumentParser(description='离线解析PostgreSQL迁移，保留全部CREATE TABLE/ALTER审计，不执行SQL')
    parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--commit',default=DEFAULT_COMMIT);parser.add_argument('--repository',default=DEFAULT_REPOSITORY);parser.add_argument('--path-prefix',default='db/migrations')
    parser.add_argument('--collection-method',choices=['supplied-files','github-textarea'],default='supplied-files',help='来源采集方式，摘要始终只覆盖本地文本副本')
    parser.add_argument('--strict',action='store_true',help='未解析结构DDL、缺失引用或文件数不符时返回非零退出码')
    parser.add_argument('--expected-files',type=int,help='可选核对迁移总数，防止不完整源码集合被误称为完整目录')
    args=parser.parse_args(argv)
    try:
        catalog=extract(args.source,args.commit,args.repository,args.path_prefix)
        catalog['source']['collection_method']=args.collection_method
        catalog['source']['collection_note']=('源码经GitHub公开文件页file content textarea提取；浏览器可能去掉末尾换行。SHA256与bytes仅是本地提取文本副本摘要及字节数，不声称Git blob原始字节完全一致。' if args.collection_method=='github-textarea' else '摘要与字节数仅对应传入本地文件；未与Git blob原始字节核验。')
        if args.expected_files is not None:
            catalog['coverage']['expected_source_files']=args.expected_files
            catalog['coverage']['collected_source_complete']=len(catalog['files'])==args.expected_files
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'output':str(args.output),'counts':catalog['counts'],'coverage':catalog['coverage']},ensure_ascii=False,indent=2))
        return 2 if args.strict and (catalog['unparsed_ddl'] or catalog['unresolved_references'] or catalog['coverage'].get('collected_source_complete') is False) else 0
    except Exception as exc:print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
