function fetchLogDataAndFillTable() {
    $.getJSON('/_fetch_log', function(data) {
        // Clear the tbody of the table
        $('#log-table tbody').empty();
        // Add results to the table
        $.each(data.logs, function(index, log) {
            var row = $('<tr>');
            row.append($('<td>').text(log.time));
            row.append($('<td>').text(log.moduleId));
            row.append($('<td>').text(log.cmd_tx));
            row.append($('<td>').text(log.cmd_rx));
            row.append($('<td>').addClass(log.status).text(log.status));
            $('#log-table tbody').append(row);
        });
    }).fail(function() {
        alert('Failed to fetch data');
    });
}

$(document).ready(function() {
    fetchLogDataAndFillTable();

    // Initialize switch states
    $('.switch').each(function() {
        const switchElement = $(this);
        const moduleId = switchElement.data('module.id');
        const switchType = switchElement.data('switch.type');

        // Get and set initial state from server
        $.getJSON('/_get_switch_status', { moduleId: moduleId, type: switchType }, function(data) {
            const initialState = data.state;
            const initialText = data.text;
            switchElement.addClass(initialState).removeClass(initialState === 'on' ? 'off' : 'on').text(initialText);
        });

        switchElement.on('click', function() {
            const isOff = switchElement.hasClass('off');
            const confirmMessage = "Module " + moduleId + ': Do you want to turn ' + (isOff ? 'on?' : 'off?');

            if (confirm(confirmMessage)) {
                $.getJSON('/_send_cmd', { moduleId: moduleId, cmdType: isOff ? 'on' : 'off' }, function(data) {
                    fetchLogDataAndFillTable();
                    if (data.isSuccess) {
                        switchElement.toggleClass('on off').text(switchType + ' ' + (isOff ? 'ON' : 'OFF'));
                    } else {
                        alert('Error: Failed');
                    }
                });
            }
        });
    });

    // Set click event for all status buttons
    $('button.status-button').on('click', function() {
        const moduleId = $(this).data('module.id');
        const tableBody = $('#module' + moduleId + 'StatusTable tbody');

        // Get and set initial state from server
        $.getJSON('/_check_status', { moduleId: moduleId }, function(data) {
            tableBody.empty();

            // Add results to the table
            $.each(data.detailStatus, function(index, status) {
                var row = $('<tr>');
                row.append($('<td>').text(status.label));
                row.append($('<td>').text(status.bit));
                row.append($('<td>').text(status.value));
                tableBody.append(row);
            });
        }).fail(function() {
            alert("Error: Failed to get data");
        });
    });

    // Set click event for all reset buttons
    $('button.reset-button').on('click', function() {
        var moduleId = $(this).data('module.id');
        if (confirm("Do you want to restart Module" + moduleId + "?")) {
            $.getJSON('/_send_cmd', { moduleId: moduleId, cmdType: "reset" }, function(data) {
                fetchLogDataAndFillTable();
                if (!data.isSuccess) {
                    alert("Error: Failed to reset Module " + moduleId);
                }
            });
        }
    });

    // Set click event for all apply buttons
    $('button.apply-button').on('click', function() {
        const moduleId = $(this).data('module.id');
        const hvType = $(this).data('hv.type');
        const hvForm = $('#module' + moduleId + hvType + 'HVForm');
        const hvValue = hvForm.val();

        if (hvValue === "") {
            alert('Error: Please input HV value');
            return;
        }

        if (confirm("Set HV of Module " + moduleId + ' to ' + hvValue + "?")) {
            $.getJSON('/_change_hv', { moduleId: moduleId, hvValue: hvValue, hvType: hvType }, function(data) {
                fetchLogDataAndFillTable();
                const statusCode = data.statusCode;

                switch (statusCode) {
                    case 0:
                        if (hvType == "Norm") {
                            $("#module" + moduleId + "TempCorrSwitch").removeClass('on').addClass('off').text('Temp OFF');
                        } else if (hvType == "Temp") {
                            $("#module" + moduleId + "V0").text(hvValue);
                        }
                        break;
                    case 1:
                        alert('Error: Failed');
                        break;
                    case 2:
                        alert('Error: Out of Range');
                        break;
                    default:
                        alert('Error: Unknown Status Code');
                }
            });
        }
        hvForm.val('');
    });
});
