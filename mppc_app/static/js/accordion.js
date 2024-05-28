$(document).ready(function() {
    const accordionDetails = '.details';
    const accordionSummary = '.details-summary';
    const accordionContent = '.details-content';
    const speed = 200;

    // Function to toggle accordion open/close state
    function toggleAccordion($summary) {
        $summary.toggleClass("is-active");
        const $details = $summary.parent(accordionDetails);
        const $content = $summary.next(accordionContent);

        if ($details.attr("open")) {
            $content.slideUp(speed, function() {
                $details.removeAttr("open");
            });
        } else {
            $details.attr("open", "true");
            $content.hide().slideDown(speed);
        }
    }

    // Event listener for summary click
    $(accordionSummary).on("click", function(event) {
        event.preventDefault();
        toggleAccordion($(this));
    });
});
