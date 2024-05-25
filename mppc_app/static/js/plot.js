function fetchMppcDataAndPlot() {
    $.getJSON($SCRIPT_ROOT + '/_fetch_mppc_data', function(data) {
        // JSONデータを解析
        var graph_data = JSON.parse(data.graph_data);

        // データの設定
        var hv1   = { x: graph_data.x, y: graph_data.y[0], xaxis: 'x1', yaxis: 'y1', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '1', name: "V1 = " + (Math.round(graph_data.y[0].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var curr1 = { x: graph_data.x, y: graph_data.y[1], xaxis: 'x1', yaxis: 'y1', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '1', name: "I1 = " + (Math.round(graph_data.y[1].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var temp1 = { x: graph_data.x, y: graph_data.y[2], xaxis: 'x1', yaxis: 'y1', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '1', name: "T1 = " + (Math.round(graph_data.y[2].slice(-1)[0]*100)/100).toString().padStart(5, ' ') };

        var hv2   = { x: graph_data.x, y: graph_data.y[3], xaxis: 'x2', yaxis: 'y2', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: "2", name: "V2 = " + (Math.round(graph_data.y[3].slice(-1)[0]*100)/100).toString().padStart(5, ' ') };
        var curr2 = { x: graph_data.x, y: graph_data.y[4], xaxis: 'x2', yaxis: 'y2', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: "2", name: "I2 = " + (Math.round(graph_data.y[4].slice(-1)[0]*100)/100).toString().padStart(5, ' ') };
        var temp2 = { x: graph_data.x, y: graph_data.y[5], xaxis: 'x2', yaxis: 'y2', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: "2", name: "T2 = " + (Math.round(graph_data.y[5].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };

        var hv3   = { x: graph_data.x, y: graph_data.y[6], xaxis: 'x3', yaxis: 'y3', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '3', name: "V3 = " + (Math.round(graph_data.y[6].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var curr3 = { x: graph_data.x, y: graph_data.y[7], xaxis: 'x3', yaxis: 'y3', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '3', name: "I3 = " + (Math.round(graph_data.y[7].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var temp3 = { x: graph_data.x, y: graph_data.y[8], xaxis: 'x3', yaxis: 'y3', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '3', name: "T3 = " + (Math.round(graph_data.y[8].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };

        var hv4   = { x: graph_data.x, y: graph_data.y[9],  xaxis: 'x4', yaxis: 'y4', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '4', name: "V4 = " + (Math.round(graph_data.y[9].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var curr4 = { x: graph_data.x, y: graph_data.y[10], xaxis: 'x4', yaxis: 'y4', mode: 'lines', type: 'scatter', line: {color: "#1f77b4"}, legendgroup: '4', name: "I4 = " + (Math.round(graph_data.y[10].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };
        var temp4 = { x: graph_data.x, y: graph_data.y[11], xaxis: 'x4', yaxis: 'y4', mode: 'lines', type: 'scatter', line: {color: "#ff7f0e"}, legendgroup: '4', name: "T4 = " + (Math.round(graph_data.y[11].slice(-1)[0]*100)/100).toString().padStart(5, ' ')  };

        var trace = [hv1, temp1, curr1, hv2, temp2, curr2, hv3, temp3, curr3, hv4, temp4, curr4];

        var layout = {
            legend:{
                title: {
                    text: graph_data.x.slice(-1)[0].toString().substring(0, 19).replace("T", " ") + "  (Unit; V [V], T [K], I [×10 mA])",
                    side: "top",
                    font:{
                        size: 18
                    },
                },
                x:0.5,
                y:1,
                xanchor:'center',
                yanchor:'bottom',
                orientation: "h",
                font:{
                    size: 18
                },
            },
            height: 800,
            grid: {rows: 2, columns: 2, pattern: 'independent'},
        };

        Plotly.newPlot('trend-graph', trace, layout);
    });
}

// ページロード時に実行
$(document).ready(function() {
    fetchMppcDataAndPlot();
    setInterval(fetchMppcDataAndPlot, 5 * 1000);
});
