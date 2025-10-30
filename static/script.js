let chartMap = {};
let portLabels = {};
let DISPLAY_TIME_WINDOW_MINUTES; // Will be set by initializeApp

/**
 * Populates UI elements like dropdowns and tables based on portLabels.
 * This runs once at startup. Assumes status panels 0-3 exist in HTML.
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

    // Handle case where no ports are configured for UI
    if (sortedPortIds.length === 0) {
        console.warn("No port labels received from API to populate UI.");
        graphToggleBody.innerHTML = '<tr><td colspan="4">No ports configured for UI</td></tr>';
        const firstPanel = document.getElementById('status-panel-0');
        if (firstPanel) firstPanel.innerHTML = '<p>No ports configured for UI display.</p>';
        portIdSelect.options.add(new Option("No Ports", ""));
        rawPortIdSelect.options.add(new Option("No Ports", ""));
        return;
    }


    sortedPortIds.forEach(portId => {
        // Ensure we only process ports intended for the UI based on filtered portLabels
        // (This check assumes main.py filters portLabels correctly)
        if (!portLabels.hasOwnProperty(portId)) return;

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
        // Assumes panels 'status-panel-0' to 'status-panel-3' exist in index.html
        const panel = document.getElementById(`status-panel-${portId}`);
        if(panel) {
            const h2 = panel.querySelector('h2');
            if (h2) {
                h2.textContent = label;
            } else {
                panel.innerHTML = `<h2>${label}</h2><p>Loading...</p>`; // Fallback
            }
             // Ensure initial loading message is present
             if (!panel.querySelector('p') && !panel.querySelector('table')) {
                 const p = document.createElement('p');
                 p.textContent = 'Loading...';
                 panel.appendChild(p);
             }
        } else {
             // Only warn if the ID is expected (0-3) but panel is missing
             if (portId >= 0 && portId <= 3) {
                console.warn(`Status panel element 'status-panel-${portId}' not found.`);
             }
        }
    });
}

/**
 * Toggles the visibility of voltage/ramp/value input fields
 * based on the selected command type.
 */
function toggleValueInput() {
    const commandType = document.getElementById('command_type').value;
    // --- MODIFIED: Use correct ID 'value-controls' ---
    const valueControls = document.getElementById('value-controls'); // Target the generic value div
    const rampOptions = document.getElementById('ramp-options');
    // --- ADDED: Get label and input elements ---
    const valueLabel = document.getElementById('value-label');     // Target the label inside value-controls
    const valueInput = document.getElementById('value');         // Target the input inside value-controls
    // --- END ADDITION ---

    // --- MODIFIED: Include Kikusui commands needing a value ---
    const needsValueCommands = [
        'SET_VOLTAGE', 'RAMP_VOLTAGE', 'SET_CURRENT', 'ENABLE_OCP'
    ];
    // --- END MODIFICATION ---

    if (needsValueCommands.includes(commandType)) {
        valueControls.style.display = 'block';
        // --- ADDED: Logic to change label and step ---
        if (commandType === 'SET_VOLTAGE' || commandType === 'RAMP_VOLTAGE') {
            valueLabel.textContent = 'Target Voltage (V)';
            valueInput.step = '0.1';
        } else if (commandType === 'SET_CURRENT' || commandType === 'ENABLE_OCP') {
            valueLabel.textContent = (commandType === 'SET_CURRENT') ? 'Target Current (A)' : 'OCP Trip Current (A)';
            valueInput.step = '0.001'; // Example step for Amps
        }
        // --- END ADDITION ---
        rampOptions.style.display = (commandType === 'RAMP_VOLTAGE') ? 'block' : 'none';
    } else {
        valueControls.style.display = 'none';
        rampOptions.style.display = 'none';
    }
}

/**
 * Sends a structured JSON command to the server.
 */
async function sendStructuredCommand() {
    const commandType = document.getElementById('command_type').value;
    const portId = parseInt(document.getElementById('port_id').value);
    if (isNaN(portId)) { showNotification("Please select a valid port.", "error"); return; } // Added check

    const payload = {
        port_id: portId,
        command_type: commandType,
        value: null, // Initialize
        ramp_steps: null,
        ramp_delay_s: null
     };

    // --- MODIFIED: Include Kikusui commands needing a value ---
    const needsValueCommands = [
        'SET_VOLTAGE', 'RAMP_VOLTAGE', 'SET_CURRENT', 'ENABLE_OCP'
    ];
    // --- END MODIFICATION ---

    if (needsValueCommands.includes(commandType)) {
        // --- MODIFIED: Use correct ID 'value' ---
        const valueInput = document.getElementById('value');
        // --- END MODIFICATION ---
        if (!valueInput.value) {
            showNotification(`Please enter a target value for ${commandType}.`, 'error'); // Use showNotification
            return;
        }
        payload.value = parseFloat(valueInput.value);
    }
    if (commandType === 'RAMP_VOLTAGE') {
        payload.ramp_steps = parseInt(document.getElementById('ramp_steps').value);
        payload.ramp_delay_s = parseFloat(document.getElementById('ramp_delay_s').value);
    }
    try {
        const response = await fetch('/serial/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (!response.ok) throw new Error(`Server error: ${response.status} ${await response.text()}`); // Include text
        const result = await response.json();
        console.log("Command Response:", result); // Added log
        showNotification(result.message || 'Command sent!'); // Use showNotification
    } catch (error) {
        console.error('Error sending command:', error); // Changed from 'Error:'
        showNotification(`Failed to send command: ${error.message}`, 'error'); // Use showNotification
    }
}

/**
 * Sends a raw string command to the server.
 */
async function sendRawCommand() {
    const portId = parseInt(document.getElementById('raw_command_port_id').value);
    if (isNaN(portId)) { showNotification("Please select a valid port.", "error"); return; } // Added check
    const payload = { port_id: portId, command: document.getElementById('raw_command').value };
    if (!payload.command) {
        showNotification('Please enter a raw command string.', 'error'); // Use showNotification
        return;
    }
    try {
        const response = await fetch('/serial/raw-command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
         if (!response.ok) throw new Error(`Server error: ${response.status} ${await response.text()}`); // Include text
        const result = await response.json();
        console.log("Raw Command Response:", result); // Added log
        showNotification(result.message || 'Raw command sent!'); // Use showNotification
    } catch (error) {
        console.error('Error sending raw command:', error); // Changed from 'Error:'
        showNotification(`Failed to send raw command: ${error.message}`, 'error'); // Use showNotification
    }
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

        updateStatusPanels(data);
        updateCharts(data);

    } catch (error) {
        console.error('Error in updateDataAndCharts:', error);
        // Display error in status panels
        const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);
        sortedPortIds.forEach(portId => {
             const panel = document.getElementById(`status-panel-${portId}`);
             // Add error class for styling
             if(panel) panel.innerHTML = `<h2>${portLabels[portId] || `Port ${portId}`}</h2><p class="error-text">Error loading data...</p>`;
        });
    }
}

/**
 * Toggles the visibility of a dataset (line) on a chart.
 * Called by the checkboxes in the "Graph Display" table.
 */
function handleGraphToggle(portId, metric, element) {
    const chart = chartMap[metric];
    const datasetIndex = chart ? chart.data.datasets.findIndex(ds => ds.portId === portId) : -1;
    if (chart && datasetIndex !== -1) {
        chart.setDatasetVisibility(datasetIndex, element.checked);
        chart.update();
    } else {
        console.warn(`Could not find dataset for portId ${portId} / metric ${metric}`);
    }
}

/**
 * Updates all status panels with the *latest* data point for each port,
 * using the detailed table layout. Assumes panels exist in HTML.
 */
function updateStatusPanels(data) {
    // Iterate only over UI ports defined in portLabels
    const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);

    sortedPortIds.forEach(portId => {
        const panel = document.getElementById(`status-panel-${portId}`);
        if (!panel) {
             // If a panel for a UI port doesn't exist, skip it
             // console.warn(`Hardcoded status panel element 'status-panel-${portId}' not found during update.`);
             return;
        }
        const label = portLabels[portId]; // Label comes from API

        // --- Use findLast() to get the newest data point ---
        // Ensure findLast exists or provide a polyfill if targeting older browsers
        const latestData = typeof data.findLast === 'function'
            ? data.findLast(d => d.port_id === portId)
            : data.slice().reverse().find(d => d.port_id === portId); // Fallback

        if (latestData) {
            const d = latestData;
            const h2 = panel.querySelector('h2');
            if (h2) {
                 h2.textContent = label;
                 h2.className = d.is_hv_on ? 'port-on' : 'port-off';
            } else {
                 panel.innerHTML = `<h2 class="${d.is_hv_on ? 'port-on' : 'port-off'}">${label}</h2>`;
            }

            const timestamp = new Date(d.timestamp).toLocaleString('ja-JP', { hour12: false });
            // Use unified names from backend
            const isOvercurrent = d.is_overcurrent;
            const isCurrentLimit = d.is_current_limit;
            const tempInRange = d.is_temp_in_range;
            const tempSensorConnected = d.is_temp_sensor_connected;
            const tempCorrEnabled = d.is_temp_correction_enabled;

            // Use the detailed table layout
            const statusHtml = `
                <table>
                    <tr><td colspan="4">${timestamp}</td></tr>
                    <tr><td colspan="4"><strong>V:</strong> ${d.voltage ?? 'N/A'}V / <strong>C:</strong> ${d.current ?? 'N/A'}mA / <strong>T:</strong> ${d.temperature ?? 'N/A'}°C</td></tr>
                    <tr>
                        <td>HV Status</td><td class="${d.is_hv_on ? 'status-ok' : 'status-warn'}">${d.is_hv_on ? 'ON' : 'OFF'}</td>
                        <td>Overcurrent</td><td class="${!isOvercurrent ? 'status-ok' : 'status-warn'}">${!isOvercurrent ? 'OK' : 'ACTIVE'}</td>
                    </tr>
                    <tr>
                        <td>Curr Limit</td><td class="${!isCurrentLimit ? 'status-ok' : 'status-warn'}">${!isCurrentLimit ? 'OK' : 'LIMIT'}</td>
                        <td>Temp. Sensor</td><td class="${tempSensorConnected === null ? '' : (tempSensorConnected ? 'status-ok' : 'status-warn')}">${tempSensorConnected === null ? 'N/A' : (tempSensorConnected ? 'OK' : 'N/C')}</td>
                    </tr>
                    <tr>
                        <td>Temp. Range</td><td class="${tempInRange === null ? '' : (tempInRange ? 'status-ok' : 'status-warn')}">${tempInRange === null ? 'N/A' : (tempInRange ? 'OK' : 'OUT')}</td>
                        <td>Temp. Corr.</td><td class="${tempCorrEnabled === null ? '' : (tempCorrEnabled ? 'status-ok' : 'status-warn')}">${tempCorrEnabled === null ? 'N/A' : (tempCorrEnabled ? 'ON' : 'OFF')}</td>
                    </tr>
                </table>
            `;

            // Replace existing content (p or table) after h2
            let contentElement = panel.querySelector('table');
            if (!contentElement) contentElement = panel.querySelector('p');
            if (contentElement) {
                contentElement.outerHTML = statusHtml;
            } else if (h2) {
                h2.insertAdjacentHTML('afterend', statusHtml);
            } else {
                panel.innerHTML += statusHtml; // Fallback
            }

        } else {
             const h2 = panel.querySelector('h2');
             if (h2) h2.textContent = label;
             let contentElement = panel.querySelector('table');
             if (!contentElement) contentElement = panel.querySelector('p');
             if (contentElement) {
                 contentElement.outerHTML = '<p>No recent data...</p>';
             } else if(h2) {
                  h2.insertAdjacentHTML('afterend', '<p>No recent data...</p>');
             } else {
                  panel.innerHTML = `<h2>${label}</h2><p>No recent data...</p>`;
             }
        }
    });
}

/**
 * Updates all chart canvases with the latest data.
 */
function updateCharts(data) {
    const TIME_WINDOW_MS = (DISPLAY_TIME_WINDOW_MINUTES || 5) * 60 * 1000;
    const maxTime = Date.now();
    const minTime = maxTime - TIME_WINDOW_MS;

    for (const [metric, chart] of Object.entries(chartMap)) {
        if (!chart) continue;

        const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);

        // Ensure chart datasets only contain UI ports
        chart.data.datasets = chart.data.datasets.filter(ds => portLabels.hasOwnProperty(ds.portId));

        sortedPortIds.forEach(portId => {
            const datasetIndex = chart.data.datasets.findIndex(ds => ds.portId === portId);
            if (datasetIndex === -1) {
                 console.warn(`Dataset for UI port ${portId} not found in chart ${metric}.`);
                 return;
            }
            const portDataFiltered = data.filter(d =>
                d.port_id === portId && d[metric] != null && new Date(d.timestamp).valueOf() >= minTime
            );
            // Ensure data is sorted for chart.js line charts
            portDataFiltered.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
            const chartData = portDataFiltered.map(d => ({ x: new Date(d.timestamp).valueOf(), y: d[metric] }));
            chart.data.datasets[datasetIndex].data = chartData;
        });

        chart.options.scales.x.min = minTime;
        chart.options.scales.x.max = maxTime;
        chart.update('none');
    }
}

/**
 * Creates a new Chart.js instance.
 */
function createChart(canvasId, yLabel, colors) {
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) {
        console.error(`Cannot create chart: Canvas element with ID '${canvasId}' not found.`);
        return null;
    }

    const sortedPortIds = Object.keys(portLabels).map(Number).sort((a, b) => a - b);

    if (sortedPortIds.length === 0) {
        console.error(`Cannot create chart ${canvasId}: No UI port labels available.`);
        return null;
    }

    return new Chart(ctx, {
        type: 'line',
        data: {
            datasets: sortedPortIds.map(portId => ({
                label: portLabels[portId], portId: portId, data: [],
                borderColor: colors[portId % colors.length],
                tension: 0.1, fill: false, pointRadius: 2, borderWidth: 2
            }))
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: {
                x: {
                    type: 'time', time: { unit: 'second', displayFormats: { second: 'HH:mm:ss' } },
                    min: Date.now() - (DISPLAY_TIME_WINDOW_MINUTES || 5) * 60 * 1000, max: Date.now()
                },
                y: { title: { display: true, text: yLabel, font: { size: 10 } }, beginAtZero: false }
            },
            plugins: { legend: { position: 'top', labels: { boxWidth: 10, padding: 8, font: { size: 10 } } } }
        }
    });
}

const chartColors = ['#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8', '#6610f2', '#fd7e14', '#6f42c1'];

// --- ADDED: Notification function (using alert for minimal change) ---
/**
 * Shows a simple notification message using alert.
 * @param {string} message - The message to display.
 * @param {string} type - 'success' (default) or 'error'.
 */
function showNotification(message, type = 'success') {
    console.log(`Notification (${type}): ${message}`);
    const prefix = type === 'error' ? '[ERROR] ' : '[SUCCESS] ';
    alert(prefix + message);
}
// --- END ADDITION ---

async function fetchQueueStatus() {
    try {
        const response = await fetch('/api/queue-status');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        const el = document.getElementById('queue-status-display');
        
        if (el) {
            const queueSize = data.queue_size || 0;
            el.textContent = `(Queue: ${queueSize})`;   
            el.style.color = '#888'; 
        }
    } catch (error) {
        console.warn('Could not fetch queue status:', error);
        const el = document.getElementById('queue-status-display');
        if (el) {
            el.textContent = '(Queue: ?)'; 
            el.style.color = '#888';
        }
    }
}


/**
 * Main application entry point. Runs once when the page loads.
 */
async function initializeApp() {
    try {
        // Fetch display window config
        const timeWindowResponse = await fetch('/api/display-window-minutes');
        if (!timeWindowResponse.ok) throw new Error('Failed to fetch display window config');
        DISPLAY_TIME_WINDOW_MINUTES = (await timeWindowResponse.json()).display_time_window_minutes;
        console.log(`Display window set to: ${DISPLAY_TIME_WINDOW_MINUTES} minutes`);

        // Fetch FILTERED port labels (Assuming main.py filters)
        const response = await fetch('/api/port-labels');
        if (!response.ok) throw new Error(`Failed to fetch port labels: ${response.status}`);
        portLabels = await response.json();
        console.log("UI Port labels received from API:", portLabels);
        if (Object.keys(portLabels).length === 0) {
             console.warn("Received EMPTY port labels from API. UI might be empty.");
             // Populate UI anyway to show "No Ports" messages
        }

        // Build UI based on FILTERED labels (updates hardcoded panels)
        populatePortSelectorsAndLabels();

        // Create charts based on FILTERED labels
        chartMap['voltage'] = createChart('voltageChart', 'Voltage (V)', chartColors);
        chartMap['current'] = createChart('currentChart', 'Current (mA)', chartColors);
        chartMap['temperature'] = createChart('tempChart', 'Temperature (°C)', chartColors);
        // Do not throw error here if charts fail, allow partial UI
        if (!chartMap['voltage'] || !chartMap['current'] || !chartMap['temperature']) {
             console.error("One or more charts failed to initialize.");
        }

        // Initial data load
        await updateDataAndCharts();
        await fetchQueueStatus();

        // Set interval for updates
        setInterval(() => {
            updateDataAndCharts();
            fetchQueueStatus();
        }, 2000);

    } catch (error) {
        console.error("Initialization failed:", error);
        alert(`Failed to initialize: ${error.message}. Check server logs and config.`);
        // Display error in a prominent place on the page as well
        const statusGrid = document.getElementById('status-grid');
        if (statusGrid) statusGrid.innerHTML = `<p class="error-text" style="grid-column: 1 / -1;">Initialization Failed: ${error.message}</p>`;

    }
}

window.onload = initializeApp;

