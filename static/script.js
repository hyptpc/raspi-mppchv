let chartMap = {};
const MAX_DATA_POINTS = 20;
let portLabels = {}; // Global object to store port labels {0: "Label 0", 1: "Label 1", ...}

// --- Functions to update UI elements with dynamic labels ---
function populatePortSelectorsAndLabels() {
    const portIdSelect = document.getElementById('port_id');
    const rawPortIdSelect = document.getElementById('raw_command_port_id');
    const graphToggleBody = document.querySelector('.graph-toggle-table tbody');

    // Clear existing options/rows first
    portIdSelect.innerHTML = '';
    rawPortIdSelect.innerHTML = '';
    graphToggleBody.innerHTML = '';

    // Sort port IDs numerically for consistent order
    const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);

    sortedPortIds.forEach(portId => {
        const label = portLabels[portId];

        // Populate dropdowns
        portIdSelect.options.add(new Option(label, portId));
        rawPortIdSelect.options.add(new Option(label, portId));

        // Populate Graph Display table
        const row = graphToggleBody.insertRow();
        row.innerHTML = `
            <td>${label}</td>
            <td><input type="checkbox" onchange="handleGraphToggle(${portId}, 'voltage', this)" checked></td>
            <td><input type="checkbox" onchange="handleGraphToggle(${portId}, 'current', this)" checked></td>
            <td><input type="checkbox" onchange="handleGraphToggle(${portId}, 'temperature', this)" checked></td>
        `;

        // Update status panel titles initially
        const panel = document.getElementById(`status-panel-${portId}`);
        if(panel) {
            const h2 = panel.querySelector('h2');
            if (h2) h2.textContent = label;
        } else {
             console.warn(`Status panel for port ${portId} not found.`);
        }
    });

    // Update chart labels (Chart.js objects must exist first)
    for (const chart of Object.values(chartMap)) {
         if (chart) {
             chart.data.datasets.forEach((dataset, index) => {
                 // Assuming dataset index matches sortedPortIds index
                 const portId = sortedPortIds[index];
                 if (portLabels[portId]) {
                     dataset.label = portLabels[portId]; // Use label from config
                 }
             });
             chart.update('none'); // Update chart to show new labels
         }
    }
}


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
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        const result = await response.json();
        alert(result.message || 'Command sent!');
    } catch (error) { console.error('Error:', error); alert(`Failed to send command: ${error.message}`); }
}

async function sendRawCommand() {
    const payload = { port_id: parseInt(document.getElementById('raw_command_port_id').value), command: document.getElementById('raw_command').value };
    if (!payload.command) { alert('Please enter a raw command string.'); return; }
    try {
        const response = await fetch('/serial/raw-command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
         if (!response.ok) throw new Error(`Server error: ${response.status}`);
        const result = await response.json();
        alert(result.message || 'Raw command sent!');
    } catch (error) { console.error('Error:', error); alert(`Failed to send raw command: ${error.message}`); }
}

async function updateDataAndCharts() {
    try {
        const response = await fetch('/data');
        if (!response.ok) { throw new Error(`HTTP error fetching data! status: ${response.status}`); }
        const data = await response.json();
        if (!Array.isArray(data)) { throw new Error("Received invalid data format from /data"); }
        updateStatusPanels(data);
        updateCharts(data);
    } catch (error) {
        console.error('Error in updateDataAndCharts:', error);
        const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
        sortedPortIds.forEach(portId => {
             const panel = document.getElementById(`status-panel-${portId}`);
             if(panel) panel.innerHTML = `<h2>${portLabels[portId] || `Port ${portId}`}</h2><p style="color:red;">Error loading data...</p>`;
        });
    }
}

function handleGraphToggle(portId, metric, element) {
    const chart = chartMap[metric];
    // Find dataset index by matching the *label* (which is now dynamic)
    const datasetIndex = chart ? chart.data.datasets.findIndex(ds => ds.label === (portLabels[portId] || `Port ${portId}`)) : -1;
    if (chart && datasetIndex !== -1) {
        chart.setDatasetVisibility(datasetIndex, element.checked);
        chart.update();
    } else {
        console.warn(`Could not find dataset for portId ${portId} / metric ${metric}`);
    }
}


function updateStatusPanels(data) {
    const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
    sortedPortIds.forEach(portId => {
        const panel = document.getElementById(`status-panel-${portId}`);
        const label = portLabels[portId] || `Port ${portId}`;
        const latestData = data.find(d => d.port_id === portId);
        if (latestData) {
            const d = latestData;
            const h2Class = d.is_hv_on ? 'port-on' : 'port-off';
            const statusHtml = `<table><tr><td colspan="4">${new Date(d.timestamp).toLocaleString('ja-JP')}</td></tr><tr><td colspan="4"><strong>V:</strong> ${d.voltage ?? 'N/A'}V / <strong>C:</strong> ${d.current ?? 'N/A'}mA / <strong>T:</strong> ${d.temperature ?? 'N/A'}°C</td></tr><tr><td>HV Status</td><td class="${d.is_hv_on ? 'status-ok' : 'status-warn'}">${d.is_hv_on ? 'ON' : 'OFF'}</td><td>Overcurrent</td><td class="${!d.is_overcurrent_protection_active ? 'status-ok' : 'status-warn'}">${!d.is_overcurrent_protection_active ? 'OK' : 'ACTIVE'}</td></tr><tr><td>Curr. Spec</td><td class="${!d.is_current_out_of_spec ? 'status-ok' : 'status-warn'}">${!d.is_current_out_of_spec ? 'OK' : 'Out'}</td><td>Temp. Sensor</td><td class="${d.is_temp_sensor_connected ? 'status-ok' : 'status-warn'}">${d.is_temp_sensor_connected ? 'OK' : 'N/C'}</td></tr><tr><td>Temp. Range</td><td class="${d.is_temp_in_range ? 'status-ok' : 'status-warn'}">${d.is_temp_in_range ? 'OK' : 'Out'}</td><td>Temp. Corr.</td><td class="${d.is_temp_correction_enabled ? 'status-ok' : 'status-warn'}">${d.is_temp_correction_enabled ? 'On' : 'Off'}</td></tr></table>`;
            panel.innerHTML = `<h2 class="${h2Class}">${label}</h2>` + statusHtml;
        } else {
             panel.innerHTML = `<h2>${label}</h2><p>No recent data...</p>`;
        }
    });
}

function updateCharts(data) {
    let overallMaxTime = 0;
    for (const [metric, chart] of Object.entries(chartMap)) {
        if (!chart) continue;
        let maxTimeForThisChart = 0;
        const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
        
        sortedPortIds.forEach(portId => {
            const datasetIndex = chart.data.datasets.findIndex(ds => ds.label === (portLabels[portId] || `Port ${portId}`));
            if (datasetIndex === -1) return;

            const portDataNewestFirst = data.filter(d => d.port_id === portId && d[metric] != null);
            const slicedData = portDataNewestFirst.slice(0, MAX_DATA_POINTS);
            slicedData.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)); // Sort chronological
            const chartData = slicedData.map(d => ({ x: new Date(d.timestamp).valueOf(), y: d[metric] }));
            chart.data.datasets[datasetIndex].data = chartData;

            if (chartData.length > 0) {
                 const lastPointTime = chartData[chartData.length - 1].x;
                 if (lastPointTime > maxTimeForThisChart) maxTimeForThisChart = lastPointTime;
            }
        });
        if (maxTimeForThisChart > overallMaxTime) overallMaxTime = maxTimeForThisChart;
    }
    const maxTime = overallMaxTime > 0 ? overallMaxTime : Date.now();
    const minTime = maxTime - (MAX_DATA_POINTS * 5 * 1000); // Estimate window
    for (const chart of Object.values(chartMap)) {
         if (chart) {
             chart.options.scales.x.min = minTime;
             chart.options.scales.x.max = maxTime;
             chart.update('none');
         }
    }
}

function createChart(canvasId, yLabel, colors) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
    return new Chart(ctx, {
        type: 'line',
        data: {
            datasets: sortedPortIds.map(portId => ({ // Create datasets based on labels IN ORDER
                label: portLabels[portId] || `Port ${portId}`, // Use label or default
                data: [], borderColor: colors[portId % colors.length],
                tension: 0.1, fill: false, pointRadius: 2, borderWidth: 2
            }))
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: { x: { type: 'time', time: { unit: 'second', displayFormats: { second: 'HH:mm:ss' } } }, y: { title: { display: true, text: yLabel, font: {size: 10} }, beginAtZero: false } },
            plugins: { legend: { position: 'top', labels: { boxWidth: 10, padding: 8, font: { size: 10 } } } }
        }
    });
}

const chartColors = ['#007bff', '#28a745', '#dc3545', '#ffc107'];

async function initializeApp() {
    try {
        const response = await fetch('/api/port-labels');
        if (!response.ok) throw new Error('Failed to fetch port labels');
        portLabels = await response.json();
        console.log("Port labels loaded:", portLabels);

        // Populate UI elements (dropdowns, table headers) *before* creating charts
        populatePortSelectorsAndLabels();

        // Create charts (will now use correct labels from portLabels)
        chartMap['voltage'] = createChart('voltageChart', 'Voltage (V)', chartColors);
        chartMap['current'] = createChart('currentChart', 'Current (mA)', chartColors);
        chartMap['temperature'] = createChart('tempChart', 'Temperature (°C)', chartColors);

        // Initial data load
        await updateDataAndCharts();

        // Set interval for updates
        setInterval(updateDataAndCharts, 5000);

    } catch (error) {
        console.error("Initialization failed:", error);
        alert(`Failed to initialize: ${error.message}. Check server logs and config.`);
    }
}

// Start the initialization process when the window loads
window.onload = initializeApp;