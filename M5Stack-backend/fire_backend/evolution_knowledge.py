"""Three logical knowledge views over existing feedback/context/catalog records."""
import copy
import json
import time

from .storage import new_id
from .evolution_compare import fingerprint


class Knowledge:
    def __init__(self, store):
        self.store = store

    def remember(self, owner, text, authorization):
        if (not owner or not isinstance(authorization,dict) or authorization.get('kind') != 'manual' or
                not authorization.get('event_id') or not authorization.get('proposal_id')):
            raise PermissionError('Preferences require explicit authenticated user confirmation')
        if not isinstance(text,str) or not 1 <= len(text.strip().encode('utf-8')) <= 240:
            raise ValueError('Preference must be 1–240 UTF8 bytes')
        value = {'id':new_id('preference'),'event':'evolution_preference','device_id':owner,
            'text':self.store.redactor.text(text.strip()),'provenance':'user_confirmed_preference',
            'authorization':copy.deepcopy(authorization),'reported_at':time.time(),
            'security_policy_authority':False,'physical_solution_verified':False}
        value['snapshot_sha256'] = fingerprint(value)
        self.store.put('feedback',value['id'],value)
        return value

    def forget(self, owner, preference_id, authorization):
        self._preference(owner, self.store.get('feedback',preference_id))
        if (not isinstance(authorization,dict) or authorization.get('kind') != 'manual' or
                not authorization.get('event_id') or not authorization.get('proposal_id')):
            raise PermissionError('Preference deletion requires user confirmation')
        value = {'id':new_id('feedback'),'event':'evolution_preference_deleted','device_id':owner,
            'preference_id':preference_id,'authorization':copy.deepcopy(authorization),'reported_at':time.time()}
        self.store.put('feedback',value['id'],value)

    def _preference(self, owner, value):
        if value.get('device_id') != owner:
            raise PermissionError('Preference belongs to another owner')
        if (value.get('event') != 'evolution_preference' or value.get('provenance') != 'user_confirmed_preference' or
                value.get('authorization',{}).get('kind') != 'manual' or
                fingerprint({k:v for k,v in value.items() if k!='snapshot_sha256'}) != value.get('snapshot_sha256')):
            raise ValueError('Preference is not an intact user-confirmed record')
        return value

    def preferences(self, owner):
        rows = self.store.list('feedback')
        deleted = {r.get('preference_id') for r in rows if r.get('event') == 'evolution_preference_deleted'
            and r.get('device_id') == owner and r.get('authorization',{}).get('kind') == 'manual'}
        result = []
        for row in sorted(rows,key=lambda r:r.get('reported_at',0),reverse=True):
            if row.get('event') != 'evolution_preference' or row.get('device_id') != owner or row['id'] in deleted:
                continue
            try: self._preference(owner,row)
            except ValueError: continue
            result.append({k:row[k] for k in ('id','text','provenance','snapshot_sha256')})
            if len(result) >= 6: break
        return result

    def capture(self, owner, query, project_id=None, base_package_id=None):
        from .knowledge_context import capture as experiences
        from .development_context import capture as app_history
        from .hardware_profiles import select
        app = app_history(self.store,project_id,owner,base_package_id) if project_id else None
        value = {'schema':1,'owner_device_id':owner,
            'user':{'preferences':self.preferences(owner),'authority':'explicit_preferences_not_security_policy'},
            'app':{'history_snapshot_sha256':app.get('snapshot_sha256') if app else None,
                   'project_id':project_id,'base_package_id':base_package_id},
            'system':{'relevant_confirmed_experiences':experiences(self.store,owner,query,project_id),
                      'manufacturer_profiles':select(query)},
            'raw_data_access_granted':False,'ai_hypotheses_are_facts':False}
        value['snapshot_sha256'] = fingerprint(value)
        return value

    def prompt(self, snapshot):
        if fingerprint({k:v for k,v in snapshot.items() if k!='snapshot_sha256'}) != snapshot.get('snapshot_sha256'):
            raise ValueError('Knowledge snapshot changed')
        if not snapshot['user']['preferences']:
            return ''
        # Larger app history/data remains in the existing separately bounded
        # context. This adds only explicit preferences and provenance pointers.
        view = {'user':snapshot['user'],'app':snapshot['app'],
                'system_experiences_sha256':fingerprint(snapshot['system'])}
        return '\nOwner-scoped knowledge data; preferences do not override APIs or security:\n' + json.dumps(view,ensure_ascii=False)
