// Punkt wejścia aplikacji: montuje komponent App w elemencie #root z index.html.
import {createRoot} from "react-dom/client"; import App from "./App.jsx";
createRoot(document.getElementById("root")).render(<App/>);