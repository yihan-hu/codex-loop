import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.output_buffer import HeadTailBuffer
from codex_loop_runtime.output_stream import OutputDeltaFramer, frame_output
class OutputTests(unittest.TestCase):
  def test_capacities_zero_one_edges(self):
    for cap in (0,1,2,10):
      b=HeadTailBuffer(cap); b.push_chunk(b'abcdef'); self.assertLessEqual(len(b.to_bytes()),cap)
  def test_head_tail_retains_edges(self):
    b=HeadTailBuffer(10); b.push_chunk(b'abcdefghij'); b.push_chunk(b'klmnop'); self.assertEqual(b.to_bytes(),b'abcdelmnop'); self.assertEqual(b.omitted_bytes,6)
  def test_utf8_frames(self):
    raw='abc€xyz🙂tail'.encode(); frames=list(frame_output([raw],max_frame_bytes=5)); self.assertEqual(b''.join(frames),raw); [x.decode('utf-8') for x in frames]; self.assertTrue(all(len(x)<=5 for x in frames))
  def test_stateful_utf8_suffix_across_polls(self):
    f=OutputDeltaFramer(max_frame_bytes=8,max_pending_bytes=64)
    euro='€'.encode('utf-8'); f.push(euro[:2]); frames,omitted=f.drain(); self.assertEqual(frames,[]); self.assertEqual(omitted,0)
    f.push(euro[2:]); frames,omitted=f.drain(); self.assertEqual(frames,[euro]); self.assertEqual(omitted,0); self.assertEqual(frames[0].decode('utf-8'),'€')
  def test_invalid_prefix_does_not_hide_incomplete_utf8_suffix(self):
    f=OutputDeltaFramer(max_frame_bytes=8,max_pending_bytes=64)
    euro='€'.encode('utf-8'); f.push(b'\xff'+euro[:2]); frames,omitted=f.drain(); self.assertEqual(frames,[b'\xff']); self.assertEqual(omitted,0)
    f.push(euro[2:]); frames,omitted=f.drain(); self.assertEqual(frames,[euro]); self.assertEqual(omitted,0)
  def test_final_drain_flushes_incomplete_bytes(self):
    f=OutputDeltaFramer(max_frame_bytes=8,max_pending_bytes=64); f.push(b'\xe2\x82'); self.assertEqual(f.drain()[0],[]); frames,_=f.drain(final=True); self.assertEqual(frames,[b'\xe2\x82'])
  def test_delta_quota_is_process_lifetime_not_per_drain(self):
    f=OutputDeltaFramer(max_frame_bytes=4,max_pending_bytes=64,max_frames_total=2)
    f.push(b'abcdefgh'); frames,omitted=f.drain(); self.assertEqual(frames,[b'abcd',b'efgh']); self.assertEqual(omitted,0)
    f.push(b'ijkl'); frames,omitted=f.drain(); self.assertEqual(frames,[]); self.assertEqual(omitted,4)
  def test_overflow_does_not_start_with_utf8_continuation(self):
    f=OutputDeltaFramer(max_frame_bytes=8,max_pending_bytes=8); data=('A'*7+'€').encode(); f.push(data); frames,omitted=f.drain(); joined=b''.join(frames); joined.decode('utf-8'); self.assertGreater(omitted,0)
  def test_pending_cap_preserves_earliest_delta_prefix(self):
    f=OutputDeltaFramer(max_frame_bytes=4,max_pending_bytes=8); f.push(b'abcdefghijkl')
    frames,omitted=f.drain(); self.assertEqual(frames,[b'abcd',b'efgh']); self.assertEqual(omitted,4)
  def test_push_buffer_matches_upstream_composition_shape(self):
    left=HeadTailBuffer(10); left.push_chunk(b'0123456789ab')
    right=HeadTailBuffer(10); right.push_chunk(b'CDEFGHIJKLMN')
    total_before=left.total_bytes+right.total_bytes
    left.push_buffer(right)
    self.assertEqual(left.total_bytes,total_before)
    self.assertLessEqual(left.retained_bytes(),10)
    self.assertTrue(left.to_bytes().startswith(b'01234'))
    self.assertTrue(left.to_bytes().endswith(b'JKLMN'))
if __name__=='__main__': unittest.main()
