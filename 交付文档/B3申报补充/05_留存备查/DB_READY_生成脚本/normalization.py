"""Loss-aware scalar normalization. No source values or answer keys are embedded."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, date, timezone, timedelta

SHANGHAI=timezone(timedelta(hours=8))

def canonical_number(value,integer=False):
    value=str(value).strip()
    if value=='':return ''
    try:n=Decimal(value)
    except InvalidOperation:raise ValueError('not a decimal')
    if not n.is_finite():raise ValueError('nonfinite number')
    if integer and n!=n.to_integral_value():raise ValueError('not an integer')
    if not n:return '0'
    s=format(n,'f')
    return s.rstrip('0').rstrip('.') if '.' in s else s

def canonical_boolean(value):
    s=str(value).strip().lower()
    if s=='':return ''
    if s in {'true','1'}:return 'true'
    if s in {'false','0'}:return 'false'
    raise ValueError('not an explicit boolean')

def canonical_time(value,default_timezone='Asia/Shanghai',date_only=False):
    value=str(value).strip()
    if not value:return ''
    if date_only:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('ambiguous date format')
        return date.fromisoformat(value).isoformat()
    if not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',value):raise ValueError('ambiguous datetime format')
    try:d=datetime.fromisoformat(value[:-1]+'+00:00' if value.endswith('Z') else value)
    except ValueError:raise ValueError('invalid datetime')
    if d.tzinfo is None:
        if default_timezone in {'Asia/Shanghai','UTC+08:00','+08:00'}:tz=SHANGHAI
        elif default_timezone in {'UTC','Z','+00:00'}:tz=timezone.utc
        else:raise ValueError('unknown source timezone')
        d=d.replace(tzinfo=tz)
    return d.astimezone(SHANGHAI).isoformat(timespec='microseconds' if d.microsecond else 'seconds')

def convert_temperature(value,unit):
    if value=='':return value,unit,''
    if unit in {'degF','°F','Fahrenheit'}:
        try:n=Decimal(canonical_number(value))
        except ValueError:return value,unit,'INVALID_NUMBER'
        v=((n-Decimal(32))*Decimal(5)/Decimal(9)).quantize(Decimal('0.000001'),rounding=ROUND_HALF_UP)
        return canonical_number(v),'degC','UNIT_F_TO_C'
    if unit in {'','degC','°C','Celsius'}:return value,unit,''
    return value,unit,'UNKNOWN_UNIT'

def group_duplicates(rows,columns):
    seen={};keep=[];duplicates=[]
    for i,row in enumerate(rows):
        key=tuple(row.get(c,'') for c in columns)
        if key in seen:duplicates.append((i,seen[key]))
        else:seen[key]=i;keep.append(i)
    return keep,duplicates
