export const judgments = {
  same: '一致', different: '不同', only_a: '仅 A 侧观察到', only_b: '仅 B 侧观察到',
  unknown: '无法比较', ambiguous: '存在歧义'
}
const names = {
  call_ids:'Call-ID', device_id:'设备编号', channel_id:'通道编号', session_type:'会话类型', session_id:'会话编号', rule_id:'规则编号',
  signal_status:'信令状态', media_status:'媒体状态', end_reason:'结束方式',
  negotiated_ip:'协商地址', negotiated_port:'协商端口', negotiated_transport:'协商传输方式',
  subject_ssrc:'Subject SSRC', sdp_ssrc:'SDP SSRC', invite_latency:'INVITE 耗时（秒）',
  sdp_negotiation_latency:'SDP 协商耗时（秒）', first_media_latency:'首媒体耗时（秒）',
  first_keyframe_latency:'首关键帧耗时（秒）', media_duration:'媒体时长（秒）',
  total_duration:'总时长（秒）', media_stream_count:'媒体流数', critical_count:'严重事件数', warning_count:'警告事件数',
  present:'观察到媒体', ssrc:'SSRC', payload_type:'载荷类型', transport:'传输方式', packet_count:'包数',
  avg_bitrate:'平均码率（kbps）', peak_bitrate:'峰值码率（kbps）', seq_gap_packets:'序号缺口（包）',
  out_of_order_count:'乱序包数', duplicate_count:'重复包数', jitter_avg:'平均抖动（ms）',
  jitter_max:'峰值抖动（ms）', max_gap:'最大静默（秒）', interruption_count:'中断数', codec:'编码',
  width:'宽', height:'高', fps:'帧率', keyframe_count:'关键帧数', has_audio:'观察到音频', rebuild:'重建结果',
  count:'事件数', severity:'最高严重级别'
}
export const fieldName = k => names[k] || k
const values = {
  success:'成功', failed:'失败', incomplete:'不完整', received:'已收到媒体', no_media:'未观察到媒体',
  undecodable:'无法解码', normal:'正常结束', abnormal:'异常结束', capture_ended:'抓包结束',
  critical:'严重', warning:'警告', info:'提示', live:'实时点播', playback:'录像回放'
}
export function formatValue(v, field) {
  if (v == null || v === '' || v === 'unknown') return '未知'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (['signal_status','media_status','end_reason','rebuild','severity','session_type'].includes(field)) {
    return values[v] || String(v)
  }
  return String(v)
}
export const groups = [
  ['信令与会话','sessions',k => !/^(negotiated_|subject_ssrc|sdp_)/.test(k)],
  ['SDP 协商','sessions',k => /^(negotiated_|subject_ssrc|sdp_)/.test(k)],
  ['媒体传输','streams',k => !codecFields.has(k)],
  ['编码与重建','streams',k => codecFields.has(k)],
  ['诊断规则','diagnostics',() => true]
]
const codecFields = new Set(['codec','width','height','fps','keyframe_count','has_audio','rebuild'])
export function allowedLink(data, side, id) {
  if (data.stale) return false
  return id == null ? data.links[side].packets : data.links[side].sessions.includes(id)
}
