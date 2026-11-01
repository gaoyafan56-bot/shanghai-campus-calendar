import unittest,datetime as dt
import scrape

class DataRegressionTests(unittest.TestCase):
 def row(self,**changes):
  r=dict(d='2026-11-04',start='14:00',end='',co='示例公司宣讲会',venue='教室A',school='上海财经大学',type='宣讲会',link='https://career.sufe.edu.cn/career/xjhxx/view/1');r.update(changes);return r
 def test_preserve_start_only(self):
  r=scrape.event('上海财经大学','2026-11-04','14:00','','公司','A','https://career.sufe.edu.cn/career/xjhxx/view/1');self.assertEqual(r['end'],'')
 def test_same_day_impossible_end_not_displayed(self):
  r=scrape.event('东华大学','2026-11-04','2026-11-04 18:00','2026-11-04 00:00','公司','A','https://ejob.dhu.edu.cn/page/preaching.html?wid=1');self.assertEqual(r['end'],'')
 def test_official_next_day_midnight_kept(self):
  r=scrape.event('东华大学','2026-11-04','2026-11-04 18:00','2026-11-05 00:00','公司','A','https://ejob.dhu.edu.cn/page/preaching.html?wid=1');self.assertEqual(r['end'],'00:00')
 def test_machine_type_zph_is_recruitment(self):
  r=scrape.event('上海大学','2026-11-04','14:00','','秋季综合供需见面','A',scrape.SOURCES['上海大学'],'ZPH');self.assertEqual(r['type'],'招聘会')
 def test_same_activity_multiple_days_kept(self):
  self.assertNotEqual(scrape.identity(self.row()),scrape.identity(self.row(d='2026-11-05')))
 def test_changed_start_replaces_old(self):
  old=[self.row()];fresh=[self.row(start='15:00')];rows,retired=scrape.reconcile(old,fresh,{'上海财经大学'},dt.datetime(2026,11,1,9,tzinfo=scrape.TZ));self.assertEqual(len(rows),1);self.assertEqual(rows[0]['start'],'15:00')
 def test_moved_future_archived_past_retained(self):
  old=[self.row(),self.row(d='2026-10-20')];fresh=[self.row(d='2026-11-06')];rows,retired=scrape.reconcile(old,fresh,{'上海财经大学'},dt.datetime(2026,11,1,9,tzinfo=scrape.TZ));self.assertEqual({r['d'] for r in rows},{'2026-10-20','2026-11-06'});self.assertEqual(len(retired),1)
 def test_failed_school_retains_known_data(self):
  old=[self.row()];rows,retired=scrape.reconcile(old,[],set(),dt.datetime(2026,11,1,9,tzinfo=scrape.TZ));self.assertEqual(rows,old);self.assertEqual(retired,[])
 def test_missing_activity_date_rejected(self):
  with self.assertRaises(ValueError):scrape.event('上海大学','','14:00','','公司','A',scrape.SOURCES['上海大学'])
 def test_external_details_fall_back_official(self):
  r=scrape.event('上海大学','2026-11-04','14:00','','公司','A','https://example.com');self.assertEqual(r['link'],scrape.SOURCES['上海大学'])

if __name__=='__main__':unittest.main()
