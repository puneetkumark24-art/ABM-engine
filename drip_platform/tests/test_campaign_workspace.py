import os,tempfile
ROOT=os.path.dirname(os.path.dirname(__file__))
os.environ["DATABASE_URL"]="sqlite:///"+os.path.join(tempfile.gettempdir(),"drip_campaign_workspace.db")
os.environ["PUBLIC_BASE_URL"]="https://track.example.invalid"
from database import Base,engine,SessionLocal
import models,models_ext as mx
from abm_platform.services import marketing,campaign_workspace as ws,marketing_ext
Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def test_campaign_workspace():
 db=SessionLocal();o=models.Organization(canonical_name="Demo Bank");db.add(o);db.flush()
 p=models.Person(full_name="Aisha Khan",primary_email="aisha@example.invalid",current_org_id=o.id,is_active=True,consent_status="opted_in");db.add(p);db.commit()
 a=marketing.create_audience(db,"Workspace audience");marketing.add_members(db,a.id,[p.id])
 c=marketing.create_campaign(db,"Workspace",a.id,"Hello {name}",'<a href="https://example.invalid/unsubscribe">Unsubscribe</a>')
 b=ws.create_brand(db,name="Decimal",primary_color="#112233",accent_color="#445566",footer_html='<a href="https://example.invalid/unsubscribe">Unsubscribe</a>')
 ws.save_campaign(db,c.id,{"brand_profile_id":b.id,"content_blocks":[{"type":"heading","text":"Hello {name}"},{"type":"button","text":"Book demo","url":"https://example.invalid/demo"}]})
 preview=ws.preview(db,c.id,p.id);assert "Aisha" in preview["html"] and "Book demo" in preview["html"]
 assert db.query(mx.EmailCampaignRevision).count()==1
 copy=ws.duplicate(db,c.id);assert copy.id!=c.id and copy.content_blocks
 assert marketing_ext.test_send(db,c.id)["status"]=="sent"
 assert ws.approve(db,c.id,"reviewer","approve").approval_status=="approved"
 assert marketing_ext.schedule_campaign(db,c.id,__import__('datetime').datetime.utcnow()).status=="scheduled"
 t=ws.create_template(db,"Welcome","Hello","Body");assert t.is_active
 try: ws.save_campaign(db,c.id,{"content_blocks":[{"type":"html","html":"<script>x</script>"}]});ws.preview(db,c.id,p.id);assert False
 except ValueError: pass
