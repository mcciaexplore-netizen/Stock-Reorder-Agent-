"""Supplier quotations, three-way matching and supporting documents."""
from datetime import date, datetime, timezone
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
import shutil

from inventory import ValidationError, amount, line_value, quantity, scaled, text
from inventory_ops import day, rounded


class Purchasing:
    def quotes(self, product_id=None, requested_qty='1'):
        qty=scaled(requested_qty,'Comparison quantity')
        with self.connect() as db:
            rows=db.execute('SELECT q.*,s.name supplier,p.item_code,p.item_name FROM quotes q JOIN suppliers s ON s.id=q.supplier_id JOIN products p ON p.id=q.product_id '+
                ('WHERE q.product_id=? ' if product_id else '')+'ORDER BY q.id DESC',(product_id,) if product_id else ()).fetchall()
            result=[]
            for r in rows:
                result.append(dict(r,comparison_qty=max(qty,r['min_qty']),comparison_total=line_value(max(qty,r['min_qty']),r['price'])+r['freight'],expired=r['valid_until']<date.today().isoformat()))
            return sorted(result,key=lambda r:(r['expired'],r['comparison_total']))

    def save_quote(self, supplier_id, product_id, reference, price, min_qty, freight, lead_days, valid_until, terms='', *, actor, token):
        price=scaled(price,'Quoted price',100); min_qty=scaled(min_qty,'Minimum quantity')
        freight=scaled(freight,'Freight',100); lead_days=scaled(lead_days,'Lead days',1)
        reference=text(reference,'Quotation reference',required=True,limit=100); valid_until=day(valid_until)
        terms=text(terms,'Terms',limit=1000)
        if min_qty<=0 or lead_days>3650:raise ValidationError('Use positive minimum quantity and lead time no longer than 3,650 days.')
        payload=['quote',supplier_id,product_id,reference,price,min_qty,freight,lead_days,valid_until,terms]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            qid=db.execute("INSERT INTO quotes(supplier_id,product_id,reference,price,min_qty,freight,lead_days,valid_until,terms,created_at) VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))",
                (supplier_id,product_id,reference,price,min_qty,freight,lead_days,valid_until,terms)).lastrowid
            self._audit(db,actor,'quotation_saved',qid,{'reference':reference})
            return self._done(db,token,payload,qid)

    def order_quote(self, quote_id, qty, *, actor, token):
        from datetime import timedelta
        qty=scaled(qty); payload=['order_quote',quote_id,qty]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            q=db.execute('SELECT q.*,s.name,s.email FROM quotes q JOIN suppliers s ON s.id=q.supplier_id WHERE q.id=?',(quote_id,)).fetchone()
            if not q or q['valid_until']<date.today().isoformat():raise ValidationError('Choose a quotation that has not expired.')
            if qty<q['min_qty']:raise ValidationError('Quantity is below the quoted minimum.')
            notes=f"Quotation {q['reference']}. Quoted freight ₹{amount(q['freight'])} is additional; record actual freight at receipt. {q['terms']}"
            oid=db.execute("INSERT INTO purchase_orders(supplier_id,supplier_name,supplier_email,notes,created_at,actor,due_date) VALUES(?,?,?,?,?,?,?)",
                (q['supplier_id'],q['name'],q['email'],notes,datetime.now(timezone.utc).isoformat(),actor,(date.today()+timedelta(days=q['lead_days'])).isoformat())).lastrowid
            db.execute('UPDATE purchase_orders SET number=? WHERE id=?',(f'PO-{date.today():%Y%m%d}-{oid:06d}',oid))
            self._replace_lines(db,oid,[{'product_id':q['product_id'],'qty':quantity(qty),'price':amount(q['price'])}])
            self._audit(db,actor,'order_from_quote',oid,{'quote':quote_id})
            return self._done(db,token,payload,oid)

    def set_order_due(self, po_id, due_date, *, actor):
        due_date=day(due_date)
        with self.connect(True) as db:
            self._order(db,po_id)
            db.execute('UPDATE purchase_orders SET due_date=? WHERE id=?',(due_date,po_id))
            self._audit(db,actor,'delivery_date_set',po_id,{'date':due_date})

    def price_history(self, product_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT o.number reference,o.created_at date,o.supplier_name supplier,l.price,l.qty,'purchase order' source
                FROM po_lines l JOIN purchase_orders o ON o.id=l.po_id WHERE l.product_id=? AND o.state NOT IN ('draft','approved','cancelled')
                UNION ALL SELECT q.reference,q.created_at,s.name,q.price,q.min_qty,'quotation' FROM quotes q JOIN suppliers s ON s.id=q.supplier_id
                WHERE q.product_id=? ORDER BY date DESC''',(product_id,product_id))]

    def bills(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT b.*,o.number po_number,o.supplier_name FROM bills b JOIN purchase_orders o ON o.id=b.po_id ORDER BY b.id DESC')]

    def save_bill(self, po_id, number, bill_date, lines, freight='0', tax='0', *, actor, token, bill_id=None):
        number=text(number,'Supplier invoice number',required=True,limit=100); bill_date=day(bill_date)
        freight=scaled(freight,'Freight / handling',100); tax=scaled(tax,'Tax',100)
        payload=['bill',po_id,number,bill_date,lines,freight,tax,bill_id]
        with self.connect(True) as db:
            prior=self._once(db,token,payload)
            if prior is not None:return prior
            order=self._order(db,po_id)
            if order['state'] not in ('sent','partial','received','cancelled'):raise ValidationError('Record bills against placed orders.')
            if bill_id:
                old=db.execute("SELECT * FROM bills WHERE id=? AND state='review'",(bill_id,)).fetchone()
                if not old or old['po_id']!=po_id:raise ValidationError('Only an unaccepted bill for this order can be corrected.')
                db.execute('UPDATE bills SET number=?,bill_date=?,freight=?,tax=? WHERE id=?',(number,bill_date,freight,tax,bill_id))
                db.execute('DELETE FROM bill_lines WHERE bill_id=?',(bill_id,))
            else:
                bill_id=db.execute("INSERT INTO bills(po_id,supplier_id,number,bill_date,freight,tax,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",(po_id,order['supplier_id'],number,bill_date,freight,tax)).lastrowid
            if not lines:raise ValidationError('Enter at least one billed line.')
            valid={l['id'] for l in order['lines']}
            for line in lines:
                qty=scaled(line['qty'],'Billed quantity'); price=scaled(line['price'],'Billed price',100)
                if line['po_line_id'] not in valid or qty<=0:raise ValidationError('Bill lines must belong to this order and have positive quantities.')
                db.execute('INSERT INTO bill_lines(bill_id,po_line_id,qty,price) VALUES(?,?,?,?)',(bill_id,line['po_line_id'],qty,price))
            self._audit(db,actor,'supplier_bill_saved',bill_id,{'number':number})
            return self._done(db,token,payload,bill_id)

    def _bill_match(self, db, bill_id):
        bill=db.execute('SELECT * FROM bills WHERE id=?',(bill_id,)).fetchone()
        if not bill:raise ValidationError('Bill no longer exists.')
        result=dict(bill); result['lines']=[]; result['issues']=[]
        rows=db.execute('''SELECT b.*,p.item_code,p.qty ordered,p.received,p.price agreed,
            COALESCE((SELECT SUM(x.qty) FROM bill_lines x JOIN bills y ON y.id=x.bill_id
            WHERE x.po_line_id=b.po_line_id AND y.state='accepted' AND y.id<>b.bill_id),0) previously_billed
            FROM bill_lines b JOIN po_lines p ON p.id=b.po_line_id WHERE b.bill_id=?''',(bill_id,)).fetchall()
        subtotal=sum(line_value(r['qty'],r['price']) for r in rows)
        remaining=bill['freight']
        for index,row in enumerate(rows):
            r=dict(row); value=line_value(r['qty'],r['price'])
            share=remaining if index==len(rows)-1 else min(remaining,rounded(bill['freight']*value,subtotal)) if subtotal else 0
            remaining-=share
            r['landed_total']=value+share
            r['landed_unit_paise']=rounded((value+share)*1000,r['qty'])
            if r['qty']+r['previously_billed']>r['received']:result['issues'].append(f"{r['item_code']}: billed quantity exceeds received and unbilled goods.")
            if r['price']!=r['agreed']:result['issues'].append(f"{r['item_code']}: billed price differs from approved order price.")
            result['lines'].append(r)
        result['subtotal']=subtotal; result['total']=subtotal+bill['freight']+bill['tax']
        return result

    def bill_match(self,bill_id):
        with self.connect() as db:return self._bill_match(db,bill_id)

    def accept_bill(self,bill_id,*,actor):
        with self.connect(True) as db:
            bill=self._bill_match(db,bill_id)
            if bill['state']!='review':raise ValidationError('This bill is already accepted.')
            if bill['issues']:raise ValidationError('Resolve discrepancies before accepting: '+' '.join(bill['issues']))
            db.execute("UPDATE bills SET state='accepted' WHERE id=?",(bill_id,))
            self._audit(db,actor,'supplier_bill_accepted',bill_id,{'total':bill['total']})

    def _attachment_entity(self,db,entity,entity_id):
        tables={'purchase_order':'purchase_orders','supplier_bill':'bills','product':'products','job':'jobs','invoice':'invoices','repair':'repairs'}
        table=tables.get(entity)
        if not table or not db.execute(f'SELECT 1 FROM {table} WHERE id=?',(entity_id,)).fetchone():
            raise ValidationError('Choose an existing record for the document.')

    def add_attachment(self,entity,entity_id,filename,content,*,actor):
        filename=Path(filename.replace('\\','/')).name
        filename=text(filename,'File name',required=True,limit=200)
        ext=Path(filename).suffix.lower()
        allowed={'.pdf':'application/pdf','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.txt':'text/plain'}
        if ext not in allowed or not isinstance(content,bytes) or not 0<len(content)<=10*1024*1024:
            raise ValidationError('Upload PDF, PNG, JPEG or text, up to 10 MB.')
        signatures={'.pdf':b'%PDF-', '.png':b'\x89PNG\r\n\x1a\n', '.jpg':b'\xff\xd8\xff', '.jpeg':b'\xff\xd8\xff'}
        if ext in signatures and not content.startswith(signatures[ext]):raise ValidationError('The file contents do not match its extension.')
        extracted=''
        if ext=='.txt':
            try:extracted=content.decode('utf-8-sig')[:50000]
            except UnicodeDecodeError:raise ValidationError('Text documents must use UTF-8.') from None
        elif ext=='.pdf':
            try:
                from pypdf import PdfReader
                reader=PdfReader(io.BytesIO(content))
                if len(reader.pages)>100:raise ValidationError('Upload a PDF with at most 100 pages.')
                extracted='\n'.join((p.extract_text() or '') for p in reader.pages[:20])[:50000]
            except ImportError:
                extracted=''
            except ValidationError:raise
            except Exception:
                raise ValidationError('The PDF could not be read. Upload an unencrypted, valid PDF.') from None
        sha=hashlib.sha256(content).hexdigest()
        with self.connect(True) as db:
            self._attachment_entity(db,entity,entity_id)
            old=db.execute('SELECT id FROM attachments WHERE entity=? AND entity_id=? AND sha256=?',(entity,entity_id,sha)).fetchone()
            if old:return old['id']
            aid=db.execute("INSERT INTO attachments(entity,entity_id,filename,mime,content,sha256,extracted_text,created_at,actor) VALUES(?,?,?,?,?,?,?,datetime('now'),?)",(entity,entity_id,filename,allowed[ext],content,sha,extracted,actor)).lastrowid
            self._audit(db,actor,'document_attached',aid,{'filename':filename,'entity':entity,'record':entity_id})
            return aid

    def attachments(self,entity,entity_id):
        with self.connect() as db:
            self._attachment_entity(db,entity,entity_id)
            return [dict(r) for r in db.execute('SELECT id,filename,mime,sha256,extracted_text,created_at,length(content) size FROM attachments WHERE entity=? AND entity_id=? ORDER BY id DESC',(entity,entity_id))]

    def attachment_content(self,attachment_id):
        with self.connect() as db:
            row=db.execute('SELECT content FROM attachments WHERE id=?',(attachment_id,)).fetchone()
            if not row:raise ValidationError('Attachment no longer exists.')
            return bytes(row['content'])

    def scan_attachment(self,attachment_id,*,actor):
        """Optional local OCR. Extracted text never posts stock or a bill automatically."""
        import os
        executable=os.getenv('TESSERACT_PATH') or shutil.which('tesseract')
        if not executable and os.name!='nt':raise ValidationError('Install local Tesseract OCR and set TESSERACT_PATH for image text extraction. PDF text extraction already runs on upload.')
        with self.connect() as db:
            row=db.execute('SELECT * FROM attachments WHERE id=?',(attachment_id,)).fetchone()
            if not row or not row['mime'].startswith('image/'):raise ValidationError('Choose a PNG or JPEG scan.')
        with tempfile.TemporaryDirectory(prefix='stocklist-ocr-') as folder:
            source=Path(folder)/('scan'+Path(row['filename']).suffix)
            source.write_bytes(row['content'])
            command=([executable,str(source),'stdout'] if executable else
                ['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).parent/'scripts'/'ocr_windows.ps1'),'-ImagePath',str(source)])
            result=subprocess.run(command,capture_output=True,timeout=60,check=False,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValidationError('The scan could not be read. Check the local OCR language installation or try a clearer image.')
            extracted=result.stdout.decode('utf-8',errors='replace')[:50000]
        with self.connect(True) as db:
            db.execute('UPDATE attachments SET extracted_text=? WHERE id=?',(extracted,attachment_id))
            self._audit(db,actor,'document_scanned',attachment_id,{})
        return extracted
