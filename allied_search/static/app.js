Start - Process "http://127.0.0.1:8080" // Press "/" to jump to the search box.
document.addEventListener("keydown", function(event) {
    var tag = (event.target.tagName || "").toLowerCase();
    if (event.key === "/" && tag !== "input" && tag !== "textarea") {
        var box = document.querySelector(".searchbox input");
        if (box) {
            event.preventDefault();
            box.focus();
            box.select();
        }
    }
});