'use strict';

const validation = {datasets: [], runs: [], form: null, result: null, tab: 'overview', busy: false};
const validationAssessments = {
  insufficient_training: ['Chưa có cấu hình đủ điều kiện', 'Không cấu hình nào đạt cả số lệnh tối thiểu và giới hạn drawdown trên train.'],
  insufficient_holdout: ['Chưa đủ lệnh trên holdout', 'Mẫu giữ lại quá ít lệnh để đáp ứng ngưỡng đã đặt.'],
  holdout_drawdown_exceeded: ['Drawdown holdout vượt ngưỡng', 'Cấu hình đã chọn không giữ được giới hạn drawdown trên dữ liệu giữ lại.'],
  holdout_positive: ['Holdout có lợi nhuận dương', 'Kết quả trên mẫu giữ lại dương sau chi phí; cần thêm các giai đoạn độc lập.'],
  holdout_non_positive: ['Holdout chưa có lợi nhuận', 'Cấu hình tốt nhất trên train không tạo lợi nhuận dương trên mẫu giữ lại.']
};
const validationMoney = n => Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const validationDate = s => esc(s.slice(0, 16).replace('T', ' '));
const validationSource = r => r.source === 'demo' ? 'Tổng hợp · không phải giá thật' : 'CSV · nguồn người dùng';

async function loadValidation() {
  try {
    [validation.datasets, validation.runs] = await Promise.all(['datasets', 'validations'].map(k => api('/api/' + k)));
  } catch (e) { toast(e.message, true); }
}

function validationField(key, label, value, min, max, step = 'any') {
  return `<div class="field"><label for="val-${key}">${label}</label><input id="val-${key}" name="${key}" type="number" min="${min}" max="${max}" step="${step}" value="${esc(value)}" required></div>`;
}

function validationPage() {
  const p = validation.form || {...state.config.backtest_defaults, ...state.config.validation_defaults,
    pair: state.pair, dataset_id: '', name: 'Kiểm định forex'};
  const disabled = validation.busy ? 'disabled' : '';
  return heading('Chiến lược có đứng vững?', 'Tách dữ liệu. Kiểm chứng giả thuyết. Đo giới hạn của kết quả.',
    '<span class="context-tag">VALIDATION WORKBENCH / v0.3</span>') + `
  <section class="validation-intro">
    <div><div class="eyebrow">TỪ BACKTEST ĐẾN KIỂM ĐỊNH</div><h2>Giữ một phần dữ liệu<br>cho câu trả lời cuối.</h2><p>Chọn cấu hình trên train. Khóa tham số. Đánh giá trên holdout theo đúng thứ tự thời gian.</p></div>
    <ol class="validation-pipeline"><li><b>01</b><span>TRAIN<small>18 cấu hình · một quy tắc chọn</small></span></li><li><b>02</b><span>HOLDOUT<small>Tài khoản mới · tham số đã khóa</small></span></li><li><b>03</b><span>STRESS TEST<small>Chi phí ×2 · lấy mẫu chuỗi lệnh</small></span></li></ol>
  </section>
  <div class="validation-layout">
    <section class="panel"><div class="panel-header"><span class="panel-title">${icon('settings')}Thiết kế kiểm định</span><span class="tiny-label">TÀI KHOẢN USD</span></div>
      <form id="validation-form" class="form-panel" aria-busy="${validation.busy}"><fieldset class="validation-fieldset" ${disabled}>
        <div class="form-grid">
          <div class="field"><label for="val-name">Tên nghiên cứu</label><input id="val-name" name="name" maxlength="100" value="${esc(p.name)}" required></div>
          <div class="field"><label for="val-pair">Cặp tiền</label><select id="val-pair" name="pair">${options(state.config.pairs, p.pair)}</select></div>
          <div class="field wide-field"><label for="val-dataset_id">Dữ liệu kiểm định</label><select id="val-dataset_id" name="dataset_id"><option value="">Mẫu tổng hợp cố định · 720 nến 1H · không phải giá thật</option>${validation.datasets.map(d => `<option value="${d.id}" ${p.dataset_id === d.id ? 'selected' : ''}>${esc(d.name)} · ${d.pair} · ${d.bars} nến${d.bars < 300 ? ' (cần ≥300)' : ''}</option>`).join('')}</select><small>CSV cần 300–3000 nến. Nguồn giá tích hợp 120 nến không đủ cho kiểm định.</small></div>
          ${validationField('train_percent', 'Tỷ lệ train (%) · phần còn lại là holdout', p.train_percent, 50, 80, 1)}
          ${validationField('min_trades', 'Số lệnh tối thiểu mỗi phần', p.min_trades, 1, 50, 1)}
          ${validationField('max_drawdown', 'Giới hạn drawdown (%)', p.max_drawdown, 1, 100)}
          ${validationField('balance', 'Vốn đầu kỳ mỗi phần (USD)', p.balance, 100, 100000000)}
          ${validationField('risk_percent', 'Rủi ro mỗi lệnh (%)', p.risk_percent, .01, 5)}
          ${validationField('leverage', 'Giới hạn đòn bẩy', p.leverage, 1, 100)}
          ${validationField('spread_pips', 'Spread khứ hồi (pip)', p.spread_pips, 0, 100)}
          ${validationField('slippage_pips', 'Trượt giá khứ hồi (pip)', p.slippage_pips, 0, 100)}
        </div>
        <details class="evidence-details"><summary>Tính tái lập của lấy mẫu chuỗi lệnh</summary><div class="form-grid">
          ${validationField('samples', 'Số lần bootstrap', p.samples, 100, 1000, 1)}
          ${validationField('seed', 'Random seed', p.seed, 0, 4294967295, 1)}
        </div></details>
        <div class="lab-actions"><button type="submit" class="button">${validation.busy ? '<span class="spinner"></span>Đang kiểm định…' : icon('play') + 'Chạy kiểm định'}</button></div>
        <p class="top-note">Xếp hạng theo lợi nhuận train sau chi phí, chỉ chọn cấu hình đủ số lệnh và không vượt drawdown. Giới hạn được đặt trước khi xem holdout.</p>
      </fieldset></form>
    </section>
    <div class="validation-aside">
      <section class="panel"><div class="panel-header"><span class="panel-title">${icon('chart')}Không gian tìm kiếm</span><span class="inline-source">18 CẤU HÌNH</span></div><div class="validation-protocol"><div><small>CHIẾN LƯỢC</small><strong>EMA Trend / RSI Reversion</strong></div><div><small>STOP LOSS</small><strong>15 / 25 / 40 pip</strong></div><div><small>REWARD / RISK</small><strong>1 / 1.5 / 2</strong></div><p>Rủi ro, đòn bẩy và chi phí giữ cố định trong quá trình tìm kiếm. Holdout không tham gia xếp hạng.</p></div></section>
      <section class="panel"><div class="panel-header"><span class="panel-title">${icon('download')}Nhập lịch sử riêng</span></div><form id="validation-dataset-form" class="form-panel"><div class="field"><label for="val-csv">CSV OHLC · cặp tiền đang chọn</label><input id="val-csv" type="file" accept=".csv,text/csv" required ${disabled}><small>time,open,high,low,close · tối đa 450 KB. Tăng dần, không trùng thời gian; timezone mặc định UTC.</small></div><button type="submit" class="button secondary full" style="margin-top:15px" ${disabled}>Nhập & chọn dữ liệu</button></form></section>
      <div class="info-box amber">Dùng lại holdout để chỉnh chiến lược sẽ làm mất tính độc lập của kiểm định. Bootstrap mô tả các chuỗi P/L lấy mẫu lại, không dự báo xác suất thắng.</div>
    </div>
  </div>
  <div id="validation-result">${validation.result ? validationResult(validation.result) : `<section class="panel empty-state validation-empty">${icon('shield')}<h3>Một kết quả tốt cần được thử thách.</h3><p>Chạy mẫu tổng hợp để khám phá quy trình, hoặc nhập lịch sử forex của bạn.</p></section>`}</div>
  ${validationHistory()}`;
}

function validationResult(r) {
  const [title, subtitle] = validationAssessments[r.assessment];
  const positive = r.assessment === 'holdout_positive';
  return `<section class="panel selected-report validation-result-panel">
    <div class="panel-header"><span class="panel-title">${icon('shield')}${esc(r.name)} · ${r.pair}</span><button class="button secondary" data-validation="export">${icon('download')}JSON</button></div>
    <div class="validation-verdict"><span class="validation-verdict-icon ${positive ? 'positive' : 'neutral'}">${icon(positive ? 'check' : 'shield')}</span><div><div class="eyebrow">KẾT QUẢ NGHIÊN CỨU / HOLDOUT</div><h2>${title}</h2><p>${subtitle}</p><small>${validationSource(r)} · Không phải phê duyệt giao dịch</small></div></div>
    <div class="validation-split"><div style="flex:${r.split.train_bars}"><strong>TRAIN <span>${r.split.train_bars} nến</span></strong><small>${validationDate(r.split.train_start)} → ${validationDate(r.split.train_end)}</small></div><div style="flex:${r.split.holdout_bars}"><strong>HOLDOUT <span>${r.split.holdout_bars} nến</span></strong><small>${validationDate(r.split.holdout_start)} → ${validationDate(r.split.holdout_end)}</small></div></div>
    <div class="validation-tabs" role="tablist" aria-label="Chi tiết kiểm định">${[['overview', 'Tổng quan'], ['candidates', '18 cấu hình'], ['method', 'Dữ liệu & phương pháp']].map(([id, label]) => `<button id="validation-tab-${id}" role="tab" aria-controls="validation-tabpanel" aria-selected="${validation.tab === id}" data-validation-tab="${id}" class="${validation.tab === id ? 'active' : ''}">${label}</button>`).join('')}</div>
    <div id="validation-tabpanel" role="tabpanel" aria-labelledby="validation-tab-${validation.tab}">${validation.tab === 'candidates' ? validationCandidates(r) : validation.tab === 'method' ? validationMethod(r) : validationOverview(r)}</div>
  </section>`;
}

function validationOverview(r) {
  if (!r.selected) return '<div class="empty-state"><h3>Không chọn cấu hình từ tập này.</h3><p>Xem bảng 18 cấu hình và kiểm tra dữ liệu, số lệnh, ngân sách rủi ro cùng giới hạn drawdown đã đặt.</p></div>';
  const t = r.selected.metrics, h = r.holdout.metrics, p = r.selected.params;
  return `<div class="validation-selection"><span class="context-tag">THAM SỐ ĐÃ KHÓA</span><strong>${p.strategy === 'ema_trend' ? 'EMA Trend' : 'RSI Reversion'}</strong><span>Stop ${p.stop_pips} pip · R/R ${p.reward_risk} · Risk ${p.risk_percent}% · Leverage ${p.leverage}×</span><button class="button ghost" data-validation="save-strategy">${icon('check')}Lưu cấu hình</button></div>
    <div class="lab-metrics validation-metrics">
      <div><small>TRAIN · lợi nhuận sau chi phí</small><strong class="mono ${cls(t.return_percent)}">${t.return_percent.toFixed(2)}%</strong><span>${t.trades} lệnh · DD ${t.max_drawdown}%</span></div>
      <div><small>HOLDOUT · lợi nhuận sau chi phí</small><strong class="mono ${cls(h.return_percent)}">${h.return_percent.toFixed(2)}%</strong><span>${validationMoney(h.net_profit)} USD · ${h.trades} lệnh</span></div>
      <div><small>HOLDOUT · drawdown theo close</small><strong class="mono">${h.max_drawdown.toFixed(2)}%</strong><span>Ngưỡng đặt trước ${r.options.max_drawdown}%</span></div>
    </div>
    <div class="validation-chart-title"><strong>Đường vốn holdout</strong><span><i class="legend-dot" style="background:var(--accent)"></i> Equity USD <i class="legend-dot" style="background:#63748a"></i> Vốn ban đầu</span></div>
    <div class="equity-chart-wrap validation-chart"><canvas id="validation-equity" role="img" aria-label="Đường vốn holdout: đầu kỳ ${p.balance} USD, cuối kỳ ${h.final_equity} USD, drawdown ${h.max_drawdown}%"></canvas></div>
    <p class="top-note validation-chart-note">${r.holdout.bars} nến đánh giá · 50 nến trước đó chỉ khởi tạo chỉ báo · ${validationSource(r)} · UTC</p>
    <div class="validation-diagnostics"><section><h3>${icon('shield')}Độ nhạy chi phí</h3><p>Cùng cấu hình và ngân sách rủi ro, tái tính lot khi chi phí tăng.</p><div class="table-wrap"><table><thead><tr><th>Spread + slippage</th><th>Return</th><th>Drawdown</th><th>Lệnh</th></tr></thead><tbody>${r.cost_stress.map(s => `<tr><td>×${s.multiplier}</td>${s.status === 'available' ? `<td class="mono ${cls(s.metrics.return_percent)}">${s.metrics.return_percent}%</td><td class="mono">${s.metrics.max_drawdown}%</td><td>${s.metrics.trades}</td>` : `<td colspan="3">${esc(s.reason)}</td>`}</tr>`).join('')}</tbody></table></div></section><section>${validationBootstrap(r.bootstrap)}</section></div>
    <details class="validation-trade-details"><summary>Nhật ký holdout · ${r.holdout.trades.length} lệnh</summary><div class="table-wrap lab-trades"><table><thead><tr><th>Mở / UTC</th><th>Chiều</th><th>Lot</th><th>P/L USD</th><th>Thoát</th></tr></thead><tbody>${r.holdout.trades.map(t => `<tr><td class="mono">${validationDate(t.opened)}</td><td>${t.direction}</td><td class="mono">${t.lots}</td><td class="mono ${cls(t.pnl)}">${validationMoney(t.pnl)}</td><td>${t.reason}</td></tr>`).join('')}</tbody></table></div></details>`;
}

function validationBootstrap(b) {
  if (b.status !== 'available') return `<h3>${icon('chart')}Lấy mẫu chuỗi lệnh</h3><p>Cần ít nhất 10 lệnh holdout đã đóng; hiện có ${b.trades || 0}. Chưa tạo phân phối từ mẫu này.</p>`;
  const max = Math.max(...b.histogram.map(v => v.count));
  return `<h3>${icon('chart')}Lấy mẫu chuỗi lệnh</h3><p>${b.samples} mẫu · khối ${b.block_length} lệnh · seed ${b.seed} · P/L USD cố định</p><div class="validation-histogram" role="img" aria-label="Phân phối lợi nhuận lấy mẫu lại, phân vị 5 ${b.return_percent['5']}%, trung vị ${b.return_percent['50']}%, phân vị 95 ${b.return_percent['95']}%">${b.histogram.map(v => `<span style="height:${Math.max(1, v.count/max*100)}%" title="${v.from.toFixed(2)}% → ${v.to.toFixed(2)}%: ${v.count} mẫu"></span>`).join('')}</div><div class="validation-quantiles">${[['5', 'P5'], ['50', 'Trung vị'], ['95', 'P95']].map(([k, label]) => `<div><small>${label} · return</small><strong class="mono">${b.return_percent[k]}%</strong></div>`).join('')}</div><p>DD phân vị 95: <strong>${b.drawdown_percent['95']}%</strong> · ${b.sample_loss_fraction_percent}% mẫu kết thúc lỗ. Đây là thống kê lấy mẫu lại, không phải xác suất tương lai; DD chỉ theo lệnh đóng.</p>`;
}

function validationCandidates(r) {
  return `<div class="validation-section-note"><p>${esc(r.selection_rule)}</p><small>Đủ điều kiện: ≥${r.options.min_trades} lệnh và DD ≤${r.options.max_drawdown}%. Tất cả số liệu trong bảng thuộc tập TRAIN.</small></div><div class="table-wrap"><table><thead><tr><th>Thứ hạng P/L</th><th>Chiến lược</th><th>Stop / RR</th><th>Return</th><th>DD</th><th>Lệnh</th><th>Điều kiện train</th></tr></thead><tbody>${r.candidates.map((c, i) => {
    const selected = r.selected && c.params.strategy === r.selected.params.strategy && c.params.stop_pips === r.selected.params.stop_pips && c.params.reward_risk === r.selected.params.reward_risk;
    return `<tr class="${selected ? 'validation-selected-row' : ''}"><td class="mono">${String(i + 1).padStart(2, '0')}${selected ? ' ✓' : ''}</td><td>${c.params.strategy === 'ema_trend' ? 'EMA Trend' : 'RSI Reversion'}</td><td class="mono">${c.params.stop_pips} / ${c.params.reward_risk}</td><td class="mono ${cls(c.metrics.return_percent)}">${c.metrics.return_percent}%</td><td class="mono">${c.metrics.max_drawdown}%</td><td>${c.metrics.trades}</td><td><span class="status-chip ${c.eligible ? 'completed' : 'failed'}">${selected ? 'Được chọn' : c.eligible ? 'Đủ điều kiện' : 'Không đạt ngưỡng'}</span></td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function validationMethod(r) {
  const q = r.quality;
  return `<div class="validation-method-grid"><section><h3>Kiểm tra cấu trúc dữ liệu</h3><div class="level-row"><span>Nến hợp lệ / UTC / tăng dần</span><strong>${q.bars}</strong></div><div class="level-row"><span>Bước thời gian trung vị</span><strong>${q.typical_interval_seconds/60} phút</strong></div><div class="level-row"><span>Khoảng cách > 1.5× trung vị</span><strong>${q.gap_count}</strong></div><div class="level-row"><span>Nến high = low</span><strong>${q.flat_bars}</strong></div><div class="level-row"><span>Close thay đổi > 3%</span><strong>${q.jumps_over_3_percent}</strong></div><div class="level-row"><span>Nến cuối tuần (UTC)</span><strong>${q.weekend_bars}</strong></div><p>${esc(q.note)}</p>${q.largest_gaps.length ? `<h3>Khoảng cách dài nhất</h3>${q.largest_gaps.map(g => `<p>${validationDate(g.after)} → ${validationDate(g.before)} · ${g.hours}h${g.includes_weekend ? ' · qua cuối tuần' : ''}</p>`).join('')}` : ''}</section><section><h3>Giả định & tính tái lập</h3><ul>${r.limitations.map(s => `<li>${esc(s)}</li>`).join('')}</ul><p>Engine ${esc(r.engine_version)} · Validation ${esc(r.validation_version)} · ${validationSource(r)}</p><small>SHA-256 · toàn bộ OHLC</small><code>${r.data_hash}</code><small>SHA-256 · chỉ OHLC train</small><code>${r.train_data_hash}</code><button class="button secondary" data-validation="export-csv">${icon('download')}Xuất snapshot OHLC</button></section></div>`;
}

function validationHistory() {
  return `<section class="panel selected-report"><div class="panel-header"><span class="panel-title">${icon('history')}Sổ kiểm định</span><span class="tiny-label">${validation.runs.length} KẾT QUẢ GẦN NHẤT</span></div>${validation.runs.length ? `<div class="table-wrap"><table><thead><tr><th>Nghiên cứu</th><th>Cặp / nguồn</th><th>Train / holdout</th><th>Đánh giá holdout</th><th>Thao tác</th></tr></thead><tbody>${validation.runs.map(r => `<tr><td><strong>${esc(r.name)}</strong><small class="validation-history-date">${validationDate(r.created)} UTC</small></td><td>${r.pair}<small class="validation-history-date">${validationSource(r)}</small></td><td class="mono">${r.split.train_bars} / ${r.split.holdout_bars}</td><td>${validationAssessments[r.assessment][0]}</td><td><div class="table-actions"><button class="button ghost" data-validation-open="${r.id}">Mở</button><button class="icon-button" data-validation-delete="${r.id}" aria-label="Xóa kiểm định ${esc(r.name)}">${icon('trash')}</button></div></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state"><p>Kết quả kiểm định sẽ được lưu cùng snapshot dữ liệu trong SQLite.</p></div>'}</section>`;
}

function captureValidation() {
  const f = $('#validation-form');
  if (!f) return validation.form;
  if (f.querySelector('fieldset').disabled) return validation.form;
  const data = Object.fromEntries(new FormData(f));
  for (const k of ['train_percent', 'min_trades', 'max_drawdown', 'samples', 'seed', 'balance', 'risk_percent', 'leverage', 'spread_pips', 'slippage_pips']) data[k] = Number(data[k]);
  validation.form = data;
  return data;
}

function drawValidationEquity() {
  const canvas = $('#validation-equity'), r = validation.result;
  if (!canvas || !r?.holdout) return;
  const values = [r.selected.params.balance, ...r.holdout.equity.map(v => v.equity)];
  const w = canvas.clientWidth, h = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
  if (!w || !h) return;
  canvas.width = w*dpr; canvas.height = h*dpr;
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const low = Math.min(...values), high = Math.max(...values), pad = Math.max((high-low)*.1, 1);
  const x = i => 14+i/(values.length-1)*(w-88);
  const y = v => h-30-(v-low+pad)/(high-low+pad*2)*(h-48);
  ctx.font = '10px monospace'; ctx.strokeStyle = '#24303e'; ctx.fillStyle = '#8998ad';
  for (let i = 0; i <= 4; i++) {
    const value = low-pad+(high-low+2*pad)*i/4;
    ctx.beginPath(); ctx.moveTo(14, y(value)); ctx.lineTo(w-68, y(value)); ctx.stroke();
    ctx.fillText(Math.round(value).toLocaleString('en-US'), w-62, y(value)+3);
  }
  ctx.setLineDash([4, 4]); ctx.strokeStyle = '#63748a';
  ctx.beginPath(); ctx.moveTo(x(0), y(values[0])); ctx.lineTo(x(values.length-1), y(values[0])); ctx.stroke();
  ctx.setLineDash([]); ctx.strokeStyle = '#42dac2'; ctx.lineWidth = 2;
  ctx.beginPath(); values.forEach((v, i) => i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))); ctx.stroke();
  ctx.lineTo(x(values.length-1), h-30); ctx.lineTo(x(0), h-30); ctx.closePath();
  const gradient = ctx.createLinearGradient(0, 0, 0, h);
  gradient.addColorStop(0, '#42dac230'); gradient.addColorStop(1, '#42dac200'); ctx.fillStyle = gradient; ctx.fill();
  ctx.fillStyle = '#8998ad'; ctx.fillText(r.holdout.start.slice(5, 16).replace('T', ' '), 14, h-8);
  ctx.textAlign = 'right'; ctx.fillText(r.holdout.end.slice(5, 16).replace('T', ' '), w-68, h-8);
}

document.addEventListener('submit', async e => {
  if (!['validation-form', 'validation-dataset-form'].includes(e.target.id)) return;
  e.preventDefault();
  if (validation.busy) return;
  const formId = e.target.id, data = captureValidation();
  const file = $('#val-csv')?.files[0];
  validation.busy = true;
  render();
  try {
    if (formId === 'validation-dataset-form') {
      if (!file || file.size > 450000) throw Error('Chọn CSV tối đa 450 KB.');
      const dataset = await api('/api/datasets', {method: 'POST', body: JSON.stringify({pair: data.pair, name: file.name, csv: await file.text()})});
      validation.form.dataset_id = dataset.id;
      toast(dataset.bars < 300 ? 'Đã nhập. Bộ dữ liệu này chưa đủ 300 nến cho kiểm định.' : 'Đã nhập và chọn bộ dữ liệu.');
    } else {
      const body = {pair: data.pair, name: data.name, dataset_id: data.dataset_id, source: 'demo',
        params: Object.fromEntries(['balance', 'risk_percent', 'leverage', 'spread_pips', 'slippage_pips'].map(k => [k, data[k]])),
        options: Object.fromEntries(['train_percent', 'min_trades', 'max_drawdown', 'samples', 'seed'].map(k => [k, data[k]]))};
      validation.result = await api('/api/validations', {method: 'POST', body: JSON.stringify(body)});
      validation.tab = 'overview';
      toast('Đã lưu kiểm định và snapshot dữ liệu.');
    }
    await loadValidation();
  } catch (error) { toast(error.message, true); }
  finally {
    validation.busy = false;
    if (state.page === 'validation') {
      render();
      if (formId === 'validation-form' && validation.result) $('#validation-result').scrollIntoView({behavior: 'smooth'});
    }
  }
});

document.addEventListener('change', e => {
  if (!e.target.closest('#validation-form')) return;
  const p = captureValidation();
  if (e.target.id === 'val-dataset_id' && p.dataset_id) {
    const d = validation.datasets.find(d => d.id === p.dataset_id);
    if (d) { validation.form.pair = d.pair; $('#val-pair').value = d.pair; }
  }
});

document.addEventListener('click', async e => {
  const tab = e.target.closest('[data-validation-tab]')?.dataset.validationTab;
  const open = e.target.closest('[data-validation-open]')?.dataset.validationOpen;
  const del = e.target.closest('[data-validation-delete]')?.dataset.validationDelete;
  const action = e.target.closest('[data-validation]')?.dataset.validation;
  if (!tab && !open && !del && !action) return;
  captureValidation();
  try {
    if (tab) { validation.tab = tab; render(); $(`#validation-tab-${tab}`).focus(); }
    if (open) { validation.result = await api('/api/validations/' + open); validation.tab = 'overview'; if (state.page === 'validation') { render(); $('#validation-result').scrollIntoView({behavior: 'smooth'}); } }
    if (del) {
      if (!confirm('Xóa kết quả kiểm định và snapshot đi kèm?')) return;
      await api('/api/validations/' + del, {method: 'DELETE'});
      if (validation.result?.id === del) validation.result = null;
      await loadValidation(); if (state.page === 'validation') render();
    }
    const r = validation.result;
    if (action === 'export' && r) labDownload(JSON.stringify(r, null, 2), `traderai-validation-${r.id.slice(0, 8)}.json`, 'application/json');
    if (action === 'export-csv' && r) labDownload(['time,open,high,low,close', ...r.input_candles.map(c => ['time', 'open', 'high', 'low', 'close'].map(k => c[k]).join(','))].join('\n'), `traderai-${r.source}-${r.id.slice(0, 8)}.csv`, 'text/csv');
    if (action === 'save-strategy' && r?.selected) {
      await api('/api/strategies', {method: 'POST', body: JSON.stringify({name: r.name + ' · train selection', pair: r.pair, params: r.selected.params})});
      toast('Đã lưu vào thư viện cấu hình của Research Lab.');
    }
  } catch (error) { toast(error.message, true); }
});

document.addEventListener('keydown', e => {
  if (!e.target.matches('[data-validation-tab]') || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  e.preventDefault();
  const tabs = [...document.querySelectorAll('[data-validation-tab]')];
  const i = tabs.indexOf(e.target);
  tabs[e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length-1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length].click();
});
window.addEventListener('resize', () => requestAnimationFrame(drawValidationEquity));
