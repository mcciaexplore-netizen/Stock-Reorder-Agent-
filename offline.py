"""Self-contained offline entry sheet. No credentials or remote resources are embedded."""
import json
from pathlib import Path


def entry_sheet(products,locations,workspace_id,batches=()):
    product_codes={p['id']:p['item_code'] for p in products}
    data=json.dumps({'products':[{'sku':p['item_code'],'name':p['item_name'],'barcode':p['barcode'] or '', 'tracking':p['tracking']} for p in products],
                     'locations':[l['name'] for l in locations], 'workspace_id':workspace_id,
                     'batches':[{'id':b['id'],'sku':product_codes[b['product_id']],'code':b['code'],'expiry':b['expiry']} for b in batches]},ensure_ascii=False).replace('<','\\u003c')
    template=(Path(__file__).parent/'assets'/'offline.html').read_text(encoding='utf-8')
    return template.replace('__STOCKLIST_DATA__',data).encode('utf-8')
