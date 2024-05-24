$(document).ready(function() {
    // 各スイッチに対して初期状態を設定
    $('.switch').each(function() {
        var switch_element = $(this);
        var module_id = switch_element.data('module-id');
        var switch_name = switch_element.attr('name');

        // 初期状態をサーバーから取得して設定
        $.get('/_get_switch_status', { module_id: module_id, name: switch_name }, function(data) {
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
                    switch_element.removeClass('off').addClass('on').text(switch_name + ' ON');
                }
            } else {
                if (confirm(switch_name + 'をオフにしますか？')) {
                    switch_element.removeClass('on').addClass('off').text(switch_name + ' OFF');
                }
            }
        });
    });
});