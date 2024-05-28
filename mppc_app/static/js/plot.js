function fetchMppcDataAndPlot() {
    $.getJSON('/_fetch_mppc_data', function(data) {
        // Define traces for each data set
        const createTrace = (x, y, xaxis, yaxis, color, group, label) => ({
            x: x,
            y: y,
            xaxis: xaxis,
            yaxis: yaxis,
            mode: 'lines',
            type: 'scatter',
            line: { color: color },
            legendgroup: group,
            name: `${label} = ${Math.round(y.slice(-1)[0] * 100) / 100}`.padStart(5, ' ')
        });

        // Create all traces
        const traces = [
            createTrace(data.x, data.y[0],  'x1', 'y1', "#1f77b4", '1', 'V1'),
            createTrace(data.x, data.y[2],  'x1', 'y1', "#ff7f0e", '1', 'T1'),
            createTrace(data.x, data.y[1],  'x1', 'y1', "#ff7f0e", '1', 'I1'),

            createTrace(data.x, data.y[3],  'x2', 'y2', "#1f77b4", '2', 'V2'),
            createTrace(data.x, data.y[5],  'x2', 'y2', "#ff7f0e", '2', 'T2'),
            createTrace(data.x, data.y[4],  'x2', 'y2', "#1f77b4", '2', 'I2'),
            
            createTrace(data.x, data.y[6],  'x3', 'y3', "#1f77b4", '3', 'V3'),
            createTrace(data.x, data.y[8],  'x3', 'y3', "#ff7f0e", '3', 'T3'),
            createTrace(data.x, data.y[7],  'x3', 'y3', "#1f77b4", '3', 'I3'),
            
            createTrace(data.x, data.y[9],  'x4', 'y4', "#1f77b4", '4', 'V4'),
            createTrace(data.x, data.y[11], 'x4', 'y4', "#ff7f0e", '4', 'T4'),
            createTrace(data.x, data.y[10], 'x4', 'y4', "#1f77b4", '4', 'I4')
        ];

        // Layout configuration
        const layout = {
            legend: {
                title: {
                    text: data.x.slice(-1)[0].toString().substring(0, 19).replace("T", " ") + "  (Unit; V [V], T [K], I [×10 mA])",
                    side: "top",
                    font: { size: 18 }
                },
                x: 0.5,
                y: 1,
                xanchor: 'center',
                yanchor: 'bottom',
                orientation: "h",
                font: { size: 18 }
            },
            height: 800,
            grid: { rows: 2, columns: 2, pattern: 'independent' }
        };

        // Plot the graph
        Plotly.newPlot('trendGraph', traces, layout);
    });
}

// Execute on page load
$(document).ready(function() {
    fetchMppcDataAndPlot();

    // Fetch interval time and set auto-refresh
    $.getJSON('/_get_interval_time', function(data) {
        const intervalTime = data.intervalTime * 1000;
        setInterval(fetchMppcDataAndPlot, intervalTime);
    });
});
