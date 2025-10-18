let chartMap = {};
const MAX_DATA_POINTS = 20; // Keep enough points for the time window
const TIME_WINDOW_MINUTES = 5; // Display the last 5 minutes
const TIME_WINDOW_MS = TIME_WINDOW_MINUTES * 60 * 1000; // Convert minutes to milliseconds

function toggleValueInput() {
    const commandType = document.getElementById('command_type').value;
    const voltageControls = document.getElementById('voltage-controls');
    const rampOptions = document.getElementById('ramp-options');
    voltageControls.style.display = (commandType === 'SET_VOLTAGE' || commandType === 'RAMP_VOLTAGE') ? 'block' : 'none';
    rampOptions.style.display = (commandType === 'RAMP_VOLTAGE') ? 'block' : 'none';
}

async function sendStructuredCommand() {
    const commandType = document.getElementById('command_type').value;
    const payload = { port_id: parseInt(document.getElementById('port_id').value), command_type: commandType };
    if (commandType === 'SET_VOLTAGE' || commandType === 'RAMP_VOLTAGE') {
        const valueInput = document.getElementById('value');
        if (!valueInput.value) { alert('Please enter a target voltage.'); return; }
        payload.value = parseFloat(valueInput.value);
    }
    if (commandType === 'RAMP_VOLTAGE') {
        payload.ramp_steps = parseInt(document.getElementById('ramp_steps').value);
        payload.ramp_delay_s = parseFloat(document.getElementById('ramp_delay_s').value);
    }
    try {
        const response = await fetch('/serial/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const result = await response.json();
        alert(result.message || 'Command sent!');
    } catch (error) { console.error('Error:', error); alert('Failed to send command.'); }
}

async function sendRawCommand() {
    const payload = { port_id: parseInt(document.getElementById('raw_command_port_id').value), command: document.getElementById('raw_command').value };
    if (!payload.command) { alert('Please enter a raw command string.'); return; }
    try {
        const response = await fetch('/serial/raw-command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const result = await response.json();
        alert(result.message || 'Raw command sent!');
    } catch (error) { console.error('Error:', error); alert('Failed to send raw command.'); }
}

async function updateDataAndCharts() {
    try {
        const response = await fetch('/data');
        if (!response.ok) { throw new Error(`HTTP error! status: ${response.status}`); }
        const data = await response.json(); // Data from API is newest-first
        updateStatusPanels(data);
        updateCharts(data); // Pass newest-first data
    } catch (error) { console.error('Error fetching or processing data:', error); }
}

function handleGraphToggle(portId, metric, element) {
    const chart = chartMap[metric];
    if (chart) { chart.setDatasetVisibility(portId, element.checked); chart.update(); }
}

function updateStatusPanels(data) { // Expects newest-first data
    for (let i = 0; i < 4; i++) {
        const panel = document.getElementById(`status-panel-${i}`);
        const latestData = data.find(d => d.port_id === i);
        if (latestData) {
            const d = latestData;
            const h2Class = d.is_hv_on ? 'port-on' : 'port-off';
            const statusHtml = `<table><tr><td colspan="4">${new Date(d.timestamp).toLocaleString('ja-JP')}</td></tr><tr><td colspan="4"><strong>V:</strong> ${d.voltage}V / <strong>C:</strong> ${d.current}mA / <strong>T:</strong> ${d.temperature}°C</td></tr><tr><td>HV Status</td><td class="${d.is_hv_on ? 'status-ok' : 'status-warn'}">${d.is_hv_on ? 'ON' : 'OFF'}</td><td>Overcurrent</td><td class="${!d.is_overcurrent_protection_active ? 'status-ok' : 'status-warn'}">${!d.is_overcurrent_protection_active ? 'OK' : 'ACTIVE'}</td></tr><tr><td>Curr. Spec</td><td class="${!d.is_current_out_of_spec ? 'status-ok' : 'status-warn'}">${!d.is_current_out_of_spec ? 'OK' : 'Out'}</td><td>Temp. Sensor</td><td class="${d.is_temp_sensor_connected ? 'status-ok' : 'status-warn'}">${d.is_temp_sensor_connected ? 'OK' : 'N/C'}</td></tr><tr><td>Temp. Range</td><td class="${d.is_temp_in_range ? 'status-ok' : 'status-warn'}">${d.is_temp_in_range ? 'OK' : 'Out'}</td><td>Temp. Corr.</td><td class="${d.is_temp_correction_enabled ? 'status-ok' : 'status-warn'}">${d.is_temp_correction_enabled ? 'On' : 'Off'}</td></tr></table>`;
            panel.innerHTML = `<h2 class="${h2Class}">Port ${i}</h2>` + statusHtml;
        } else { panel.innerHTML = `<h2>Port ${i}</h2><p>No recent data...</p>`; }
    }
}

// ▼▼▼ This is the updated charting function with time window ▼▼▼
function updateCharts(data) { // Expects newest-first data
    let overallMaxTime = 0; // Find the latest timestamp across all data

    // Find the latest timestamp in the current data batch
    if (data.length > 0) {
        // Since data is newest-first, the first element has the latest time
        overallMaxTime = new Date(data[0].timestamp).valueOf();
    } else {
        // If no data, use current time as max to avoid errors
        overallMaxTime = Date.now();
    }

    // Calculate the time window
    const minTime = overallMaxTime - TIME_WINDOW_MS;
    const maxTime = overallMaxTime;

    for (const [metric, chart] of Object.entries(chartMap)) {
        if (!chart) continue;
        for (let i = 0; i < 4; i++) {
            // 1. Filter data for the port and metric (newest-first)
            const portDataNewestFirst = data.filter(d => d.port_id === i && d[metric] != null);
            
            // 2. Filter data within the time window
            const windowData = portDataNewestFirst.filter(d => {
                const timestamp = new Date(d.timestamp).valueOf();
                return timestamp >= minTime && timestamp <= maxTime;
            });

            // 3. Sort this windowed data chronologically (oldest first)
            windowData.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

            // 4. Map to Chart.js format
            chart.data.datasets[i].data = windowData.map(d => ({ x: new Date(d.timestamp).valueOf(), y: d[metric] }));
        }

        // 5. Set the x-axis limits
        chart.options.scales.x.min = minTime;
        chart.options.scales.x.max = maxTime;

        // 6. Update the chart
        chart.update('none');
    }
}
// ▲▲▲ End of update ▲▲▲

function createChart(canvasId, yLabel, colors) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'line', data: { datasets: Array.from({ length: 4 }, (_, i) => ({ label: `P${i}`, data: [], borderColor: colors[i], tension: 0.1, fill: false, pointRadius: 2, borderWidth: 2 })) },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'second', displayFormats: { second: 'HH:mm:ss' } },
                    // Set min and max dynamically later in updateCharts
                },
                y: { title: { display: true, text: yLabel, font: {size: 10} }, beginAtZero: false }
            },
            plugins: { legend: { position: 'top', labels: { boxWidth: 10, padding: 8, font: { size: 10 } } } }
        }
    });
}

window.onload = () => {
    const colors = ['#007bff', '#28a745', '#dc3545', '#ffc107'];
    chartMap['voltage'] = createChart('voltageChart', 'Voltage (V)', colors);
    chartMap['current'] = createChart('currentChart', 'Current (mA)', colors);
    chartMap['temperature'] = createChart('tempChart', 'Temperature (°C)', colors);
    
    updateDataAndCharts(); // Initial load
    setInterval(updateDataAndCharts, 5000); // Refresh interval
};