// Format value to 2 decimal places and pad start to 5 characters
function formattedValue(data) {
    return (Math.round(data * 100) / 100).toString().padStart(5, ' ');
}

// Create a trace for the plot
function createTrace(x, y, xaxis, yaxis, color, group, label) {
    return {
        x: x,
        y: y,
        xaxis: xaxis,
        yaxis: yaxis,
        mode: 'lines',
        type: 'scatter',
        line: { color: color },
        legendgroup: group,
        hoverlabel: { bgcolor: '#41454c', align: "left" },
        hovertemplate: label + ' = %{y}<br>%{x}<extra></extra>'
    };
}

// Fetch data and plot the graph and table
function fetchMppcDataAndPlot() {
    $.getJSON('/_fetch_mppc_data', function (data) {
        // Generate traces for the plot
        const traces = [];
        const modules = ['Module1', 'Module2', 'Module3', 'Module4'];
        const colors = ["#1f77b4", "#ff7f0e", '#2ca02c'];
        const labels = ['HV', 'Temp', 'Curr(×10)'];

        modules.forEach((module, i) => {
            traces.push(createTrace(data.x, data.y[i * 3],     `x${i + 1}`, `y${i + 1}`, colors[0], `${i + 1}`, labels[0]));
            traces.push(createTrace(data.x, data.y[i * 3 + 1], `x${i + 1}`, `y${i + 1}`, colors[1], `${i + 1}`, labels[1]));
            traces.push(createTrace(data.x, data.y[i * 3 + 2], `x${i + 1}`, `y${i + 1}`, colors[2], `${i + 1}`, labels[2]));
        });

        // Layout configuration
        const layout = {
            showlegend: false,
            height: 750,
            grid: { rows: 2, columns: 2, pattern: 'independent', xgap: 0.1, ygap: 0.2 },
            margin: { t: 20, l: 45, r: 45 },
            annotations: modules.map((module, i) => ({
                showarrow: false,
                font: { size: 18 },
                bordercolor: "black",
                borderwidth: 2,
                xref: `x${i + 1} domain`,
                yref: `y${i + 1} domain`,
                x: 0.01,
                y: 0.95,
                xanchor: "left",
                yanchor: "bottom",
                text: `<b>${module}</b>`
            }))
        };

        // Plot the graph
        Plotly.newPlot('trendGraph', traces, layout, {
            toImageButtonOptions: {
                format: 'png',
                filename: "monitor_trend_" + data.x.slice(-1)[0].toString().substring(0, 19).replace("T", "_"),
                scale: 1
            }
        });

        // Prepare table data
        const tableTrace = [{
            type: 'table',
            header: {
                values: [[""], ["<b>HV [V]</b>"], ["<b>Temp [deg]</b>"], ["<b>Curr [×10 mA]</b>"]],
                align: "center",
                line: { width: 0 },
                fill: { color: "grey" },
                font: { size: 16, color: "white" },
            },
            cells: {
                values: [
                    modules,
                    modules.map((_, i) => formattedValue(data.y[i * 3].slice(-1)[0])),
                    modules.map((_, i) => formattedValue(data.y[i * 3 + 1].slice(-1)[0])),
                    modules.map((_, i) => formattedValue(data.y[i * 3 + 2].slice(-1)[0]))
                ],
                align: "center",
                line: { width: 0 },
                font: { size: 18, color: ["black"] },
                height: 30
            }
        }];

        // Table layout configuration
        const tableLayout = {
            title: {
                text: data.x.slice(-1)[0].toString().substring(0, 19).replace("T", " "),
                xanchor: "left",
                xref: "paper",
                x: 0,
                yanchor: "top",
                yref: "container",
                y: 0.95,
                font: { size: 20 }
            },
            margin: { t: 30, b: 10, l: 35, r: 35 },
            height: 200
        };

        // Plot the table
        Plotly.newPlot('myTable', tableTrace, tableLayout, {
            toImageButtonOptions: {
                format: 'png',
                filename: "monitor_table_" + data.x.slice(-1)[0].toString().substring(0, 19).replace("T", "_"),
                scale: 1
            }
        });
    });
}

// Execute on page load
$(document).ready(function () {
    fetchMppcDataAndPlot();

    // Fetch interval time and set auto-refresh
    $.getJSON('/_get_interval_time', function (data) {
        const intervalTime = data.intervalTime * 1000;
        setInterval(fetchMppcDataAndPlot, intervalTime);
    });
});
