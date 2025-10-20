let chartMap = {};
let portLabels = {};
let DISPLAY_TIME_WINDOW_MINUTES; // Will be set by initializeApp

/**
 * Populates UI elements like dropdowns and tables based on portLabels.
 * This runs once at startup.
 */
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
    // The dead-code loop for updating chart labels has been removed.
}

/**
 * Toggles the visibility of voltage/ramp input fields
 * based on the selected command type.
 */
function toggleValueInput() {
    const commandType = document.getElementById('command_type').value;
    const voltageControls = document.getElementById('voltage-controls');
    const rampOptions = document.getElementById('ramp-options');
    voltageControls.style.display = (commandType === 'SET_VOLTAGE' || commandType === 'RAMP_VOLTAGE') ? 'block' : 'none';
    rampOptions.style.display = (commandType === 'RAMP_VOLTAGE') ? 'block' : 'none';
}

/**
 * Sends a structured JSON command to the server.
 */
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

/**
 * Sends a raw string command to the server.
 */
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

/**
 * Main update loop. Fetches data from the server
 * and calls functions to update panels and charts.
 */
async function updateDataAndCharts() {
    try {
        const response = await fetch('/data');
        if (!response.ok) { throw new Error(`HTTP error fetching data! status: ${response.status}`); }
        const data = await response.json();
        if (!Array.isArray(data)) { throw new Error("Received invalid data format from /data"); }
        
        // Call the two update functions
        updateStatusPanels(data);
        updateCharts(data);
        
    } catch (error) {
        console.error('Error in updateDataAndCharts:', error);
        // Display error in status panels
        const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
        sortedPortIds.forEach(portId => {
             const panel = document.getElementById(`status-panel-${portId}`);
             if(panel) panel.innerHTML = `<h2>${portLabels[portId] || `Port ${portId}`}</h2><p style="color:red;">Error loading data...</p>`;
        });
    }
}

/**
 * Toggles the visibility of a dataset (line) on a chart.
 * Called by the checkboxes in the "Graph Display" table.
 */
function handleGraphToggle(portId, metric, element) {
    const chart = chartMap[metric];
    
    // Find the dataset using the robust portId, not the string label
    const datasetIndex = chart ? chart.data.datasets.findIndex(ds => ds.portId === portId) : -1;
    
    if (chart && datasetIndex !== -1) {
        chart.setDatasetVisibility(datasetIndex, element.checked);
        chart.update();
    } else {
        console.warn(`Could not find dataset for portId ${portId} / metric ${metric}`);
    }
}

/**
 * Updates all status panels with the *latest* data point for each port.
 */
function updateStatusPanels(data) {
    const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
    
    sortedPortIds.forEach(portId => {
        const panel = document.getElementById(`status-panel-${portId}`);
        const label = portLabels[portId] || `Port ${portId}`;
        
        // --- ★ BUG FIX ★ ---
        // Use findLast() to get the *newest* data point for this port
        // (because the server (new main.py) sends data sorted oldest-to-newest).
        // This fixes the mismatch between the status panel and the chart.
        const latestData = data.findLast(d => d.port_id === portId);
        
        if (latestData) {
            const d = latestData;
            const h2Class = d.is_hv_on ? 'port-on' : 'port-off';
            // Display timestamp in Japan locale
            const statusHtml = `<table><tr><td colspan="4">${new Date(d.timestamp).toLocaleString('ja-JP')}</td></tr><tr><td colspan="4"><strong>V:</strong> ${d.voltage ?? 'N/A'}V / <strong>C:</strong> ${d.current ?? 'N/A'}mA / <strong>T:</strong> ${d.temperature ?? 'N/A'}°C</td></tr><tr><td>HV Status</td><td class="${d.is_hv_on ? 'status-ok' : 'status-warn'}">${d.is_hv_on ? 'ON' : 'OFF'}</td><td>Overcurrent</td><td class="${!d.is_overcurrent_protection_active ? 'status-ok' : 'status-warn'}">${!d.is_overcurrent_protection_active ? 'OK' : 'ACTIVE'}</td></tr><tr><td>Curr. Spec</td><td class="${!d.is_current_out_of_spec ? 'status-ok' : 'status-warn'}">${!d.is_current_out_of_spec ? 'OK' : 'Out'}</td><td>Temp. Sensor</td><td class="${d.is_temp_sensor_connected ? 'status-ok' : 'status-warn'}">${d.is_temp_sensor_connected ? 'OK' : 'N/C'}</td></tr><tr><td>Temp. Range</td><td class="${d.is_temp_in_range ? 'status-ok' : 'status-warn'}">${d.is_temp_in_range ? 'OK' : 'Out'}</td><td>Temp. Corr.</td><td class="${d.is_temp_correction_enabled ? 'status-ok' : 'status-warn'}">${d.is_temp_correction_enabled ? 'On' : 'Off'}</td></tr></table>`;
            panel.innerHTML = `<h2 class="${h2Class}">${label}</h2>` + statusHtml;
        } else {
             panel.innerHTML = `<h2>${label}</h2><p>No recent data...</p>`;
        }
    });
}

/**
 * Updates all chart canvases with the latest data.
 * It filters data based on the global DISPLAY_TIME_WINDOW_MINUTES.
 * The X-axis always moves towards "now" (Date.now()).
 */
function updateCharts(data) {
    
    // Calculate the fixed time window for the X-axis
    // DISPLAY_TIME_WINDOW_MINUTES is a global var set during init
    // Use a 5-minute fallback just in case it's not set yet
    const TIME_WINDOW_MS = (DISPLAY_TIME_WINDOW_MINUTES || 5) * 60 * 1000; 
    
    // Use the browser's current time as the right edge (maxTime)
    const maxTime = Date.now();
    // Calculate the left edge (minTime) based on "now"
    const minTime = maxTime - TIME_WINDOW_MS;

    // Loop through each chart (e.g., 'voltage', 'current')
    for (const [metric, chart] of Object.entries(chartMap)) {
        if (!chart) continue; // Skip if chart object doesn't exist
        
        const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
        
        // Loop through each portId to update its corresponding dataset (line)
        sortedPortIds.forEach(portId => {
            
            // Find the dataset using the robust portId, not the label
            const datasetIndex = chart.data.datasets.findIndex(ds => ds.portId === portId);
            
            if (datasetIndex === -1) {
                console.warn(`Dataset for portId ${portId} not found in chart ${metric}`);
                return;
            }

            // Filter the raw data by time window, not by MAX_DATA_POINTS
            const portDataFiltered = data.filter(d => 
                d.port_id === portId &&       // Match the correct port
                d[metric] != null &&          // Ensure the value exists
                new Date(d.timestamp).valueOf() >= minTime // Keep data within the time window
            );
            
            // Sort the filtered data chronologically (oldest -> newest)
            portDataFiltered.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)); 
            
            // Convert to Chart.js {x, y} format
            const chartData = portDataFiltered.map(d => ({ 
                x: new Date(d.timestamp).valueOf(), 
                y: d[metric] 
            }));
            
            // Assign the new filtered data array to the chart
            chart.data.datasets[datasetIndex].data = chartData;
        }); // end forEach(portId)

        // Set the X-axis (time) display range for the chart
        chart.options.scales.x.min = minTime;
        chart.options.scales.x.max = maxTime;
        
        // Redraw the chart without animation
        chart.update('none');

    } // end for(chart)
}

/**
 * Creates a new Chart.js instance.
 * @param {string} canvasId - The ID of the HTML canvas element.
 * @param {string} yLabel - The label to display on the Y-axis.
 * @param {string[]} colors - An array of colors for the datasets.
 * @returns {Chart} The new Chart object.
 */
function createChart(canvasId, yLabel, colors) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
    
    return new Chart(ctx, {
        type: 'line',
        data: {
            // Create one dataset (line) for each port, in order
            datasets: sortedPortIds.map(portId => ({
                label: portLabels[portId] || `Port ${portId}`, // Legend label
                portId: portId, // Store portId for robust data linking
                data: [], // Data will be populated by updateCharts
                borderColor: colors[portId % colors.length],
                tension: 0.1,
                fill: false,
                pointRadius: 2,
                borderWidth: 2
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false, // Disable animation for performance
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'second',
                        displayFormats: { second: 'HH:mm:ss' }
                    }
                },
                y: {
                    title: { display: true, text: yLabel, font: { size: 10 } },
                    beginAtZero: false // Y-axis doesn't need to start at 0
                }
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { boxWidth: 10, padding: 8, font: { size: 10 } }
                }
            }
        }
    });
}

// Add more colors in case there are many ports
const chartColors = ['#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8', '#6610f2', '#fd7e14', '#6f42c1'];

/**
 * Main application entry point. Runs once when the page loads.
 */
async function initializeApp() {
    try {
        // --- 1. Fetch the display window configuration ---
        const timeWindowResponse = await fetch('/api/display-window-minutes'); 
        if (!timeWindowResponse.ok) throw new Error('Failed to fetch display window config');
        // Set the global variable
        DISPLAY_TIME_WINDOW_MINUTES = (await timeWindowResponse.json()).display_time_window_minutes;
        console.log(`Display window set to: ${DISPLAY_TIME_WINDOW_MINUTES} minutes`);

        // --- 2. Fetch port labels ---
        const response = await fetch('/api/port-labels');
        if (!response.ok) throw new Error('Failed to fetch port labels');
        portLabels = await response.json();
        console.log("Port labels loaded:", portLabels);

        // --- 3. Build UI (dropdowns, tables) ---
        // This must run *before* createChart
        populatePortSelectorsAndLabels();

        // --- 4. Create charts ---
        // This must run *after* populatePortSelectorsAndLabels
        chartMap['voltage'] = createChart('voltageChart', 'Voltage (V)', chartColors);
        chartMap['current'] = createChart('currentChart', 'Current (mA)', chartColors);
        chartMap['temperature'] = createChart('tempChart', 'Temperature (°C)', chartColors);

        // --- 5. Initial data load ---
        await updateDataAndCharts();

        // --- 6. Set interval for updates ---
        setInterval(updateDataAndCharts, 5000); // Update every 5 seconds

    } catch (error) {
        console.error("Initialization failed:", error);
        alert(`Failed to initialize: ${error.message}. Check server logs and config.`);
    }
}

// Start the initialization process when the window loads
window.onload = initializeApp;