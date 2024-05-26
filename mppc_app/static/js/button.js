function fetchLogDataAndFillTable() {
    $.getJSON('/_fetch_log', function(data) {
        // テーブルのtbodyを空にする
        $('#log-table tbody').empty();
        // 結果をテーブルに追加
        $.each(data.logs, function(index, log) {
            var row = $('<tr>');
            row.append($('<td>').text(log.time));
            row.append($('<td>').text(log.module_id));
            row.append($('<td>').text(log.cmd_tx));
            row.append($('<td>').text(log.cmd_rx));
            row.append($('<td>').addClass(log.status).text(log.status));
            $('#log-table tbody').append(row);
        });
    }).fail(function() {
        alert('データの取得に失敗しました');
    });
}

// スイッチ
$(document).ready(function() {
    fetchLogDataAndFillTable();
    // 各スイッチに対して初期状態を設定
    $('.switch').each(function() {
        var switch_element = $(this);
        var module_id = switch_element.data('module-id');
        var switch_name = switch_element.attr('name');

        // 初期状態をサーバーから取得して設定
        $.getJSON('/_get_switch_status', { module_id: module_id, name: switch_name }, function(data) {
            var initial_state = data.state;
            var initial_text = data.text;

            if (initial_state === 'on') {
                switch_element.addClass('on').removeClass('off').text(initial_text);
            } else {
                switch_element.addClass('off').removeClass('on').text(initial_text);
            }
        });

        // クリックイベントを設定
        switch_element.on('click', function() {
            // 'off'クラスがあるかを確認
            if (switch_element.hasClass('off')) {
                if (confirm(switch_name + 'をオンにしますか？')) {
                    $.getJSON('/_send_cmd', { module_id: module_id, cmd_type: "on" }, function(data) {
                        fetchLogDataAndFillTable();
                        var is_success = data.is_success;
                        if (is_success) {
                            switch_element.removeClass('off').addClass('on').text(switch_name + ' ON');
                        } else {
                            alert('失敗');
                        }
                    });
                }
            } else {
                if (confirm(switch_name + 'をオフにしますか？')) {
                    $.getJSON('/_send_cmd', { module_id: module_id, cmd_type: "off" }, function(data) {
                        fetchLogDataAndFillTable();
                        var is_success = data.is_success;
                        if (is_success) {
                            switch_element.removeClass('on').addClass('off').text(switch_name + ' OFF');
                        } else {
                            alert('失敗');
                        }
                    });
                }
            }
        });
    });
});


// ボタン
$(document).ready(function() {
    // 全てのボタンに対してクリックイベントを設定
    $('button.status-button').on('click', function() {
        var moduleId = $(this).data('module-id');
        
        // 対応するテーブルのtbodyを特定する
        var tableBody = $('#status-table-' + moduleId + ' tbody');
        
        // サーバーから初期状態を取得して設定
        $.getJSON('/_check_status', { module_id: moduleId }, function(data) {
            // テーブルのtbodyを空にする
            tableBody.empty();
            
            // 結果をテーブルに追加
            $.each(data.detail_status, function(index, status) {
                var row = $('<tr>');
                row.append($('<td>').text(status.label));
                row.append($('<td>').text(status.bit));
                row.append($('<td>').text(status.value));
                tableBody.append(row);
            });
        }).fail(function() {
            alert('データの取得に失敗しました');
        });
    });


    $('button.reset-button').on('click', function() {
        var moduleId = $(this).data('module-id');
        if (confirm("module" + moduleId + 'を再起動しますか？')) {
            $.getJSON('/_send_cmd', { module_id: moduleId, cmd_type: "reset" }, function(data) {
                fetchLogDataAndFillTable();
                var is_success = data.is_success;
                if (!is_success) {
                    alert('失敗');
                }
            });
        }
    });
    
});

// フォーム関係
$(document).ready(function() {
    $('button.apply-button').on('click', function() {
        var moduleId = $(this).data('module-id');
        var type     = $(this).data('hv-type');

        // 対応するテーブルのtbodyを特定する
        var hvForm = $('#hv-form-' + type + "-" + moduleId);
        var hvValue = hvForm.val();

        if (hvValue === "") {
            alert('エラー: HVの値を入力してください');
        } else if (confirm("module" + moduleId + 'のhvを' + hvValue + "にしますか？")) {
            $.getJSON('/_change_hv', { module_id: moduleId, hv_value: hvValue, name: type }, function(data) {
                var statusCode = data.status_code;
                fetchLogDataAndFillTable();
                if (type == "temp") {
                    $("#v0-module1").text(hvValue);
                }
                if (statusCode == 1) {
                    alert('失敗');
                } else if ( statusCode == 2 ) {
                    alert('Error: Out of Range');
                }
            });
        }
        hvForm.val('');
    });
});