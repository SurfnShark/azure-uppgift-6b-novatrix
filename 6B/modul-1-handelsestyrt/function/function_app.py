"""Azure-notis när ett nytt Novatrix-ärende sparas i privat Blob Storage."""
import json
import logging
import os
import re
from datetime import datetime, timezone

import azure.functions as func
from azure.identity import ManagedIdentityCredential
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobClient
from azure.communication.email import EmailClient
from azure.core.exceptions import ResourceExistsError

app = func.FunctionApp()


def make_notice(raw, blob_name):
    record = json.loads(raw)
    ticket = record.get('id', '')
    if not isinstance(ticket, str) or not re.fullmatch(r'[a-f0-9]{32}', ticket):
        raise ValueError('Ärendenummer måste vara 32 hextecken.')
    if not blob_name.endswith('/' + ticket + '/arende.json'):
        raise ValueError('Ärendenumret matchar inte filnamnet.')
    for field, limit in [('name', 100), ('email', 254), ('message', 4000)]:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError('Ärendets obligatoriska uppgifter är felaktiga.')
    # Notisen innehåller ingen kundtext, e-post eller bilaga.
    return {'schemaVersion': '1.0', 'ticketId': ticket, 'type': 'NewTicket',
            'message': 'Nytt Novatrix-ärende finns för behandling.',
            'blobName': ticket + '/arende.json'}


@app.function_name(name='NotifyOnTicket')
@app.blob_trigger(arg_name='ticket_blob', path='arenden/{ticket}/arende.json',
                  connection='TicketStorage', source='EventGrid')
def notify_on_ticket(ticket_blob: func.InputStream):
    if ticket_blob.length is not None and ticket_blob.length > 20000:
        raise ValueError('Ärendefilen är för stor.')
    notice = make_notice(ticket_blob.read(), ticket_blob.name)
    with ManagedIdentityCredential(client_id=os.environ['MANAGED_IDENTITY_CLIENT_ID']) as credential:
        audit_url = os.environ['AUDIT_CONTAINER_URL'] + '/' + notice['ticketId'] + '.json'
        with BlobClient.from_blob_url(audit_url, credential=credential) as audit:
            initial = {'ticketId':notice['ticketId'], 'queueSent':False, 'emailSent':False}
            try:
                audit.upload_blob(json.dumps(initial), overwrite=False)
            except ResourceExistsError:
                pass
            # Lease serializes concurrent deliveries. A send can still have an uncertain outcome.
            lease = audit.acquire_lease(lease_duration=60)
            try:
                state = json.loads(audit.download_blob(lease=lease).readall())
                if not state['queueSent']:
                    with QueueClient.from_queue_url(os.environ['NOTICE_QUEUE_URL'], credential=credential) as queue:
                        queue.send_message(json.dumps(notice, ensure_ascii=False), time_to_live=86400)
                    state['queueSent'] = True
                    audit.upload_blob(json.dumps(state), overwrite=True, lease=lease)
                if not state['emailSent']:
                    lease.renew()
                    with EmailClient(os.environ['EMAIL_ENDPOINT'], credential) as email:
                        result = email.begin_send({
                            'senderAddress':os.environ['EMAIL_SENDER'],
                            'recipients':{'to':[{'address':os.environ['NOTIFICATION_EMAIL']}]},
                            'content':{'subject':'Novatrix labbärende ' + notice['ticketId'],
                                       'plainText':'Ett nytt påhittat labbärende finns för behandling. Ärendenummer: ' + notice['ticketId']}
                        }).result(timeout=40)
                    if result.get('status') != 'Succeeded':
                        raise RuntimeError('Mejlsändningen kunde inte bekräftas.')
                    state['emailSent'] = True
                    state['emailOperationId'] = result.get('id')
                    state['completedAt'] = datetime.now(timezone.utc).isoformat()
                    audit.upload_blob(json.dumps(state), overwrite=True, lease=lease)
            finally:
                lease.release()
    logging.info('NOVATRIX_NOTICE_SENT ticketId=%s', notice['ticketId'])
